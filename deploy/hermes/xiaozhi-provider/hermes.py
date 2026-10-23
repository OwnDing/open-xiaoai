"""xiaozhi-esp32-server LLM provider for Hermes Agent, with a tool-call guard.

Mounted into the server as core/providers/llm/hermes/hermes.py and selected
with `type: hermes` in data/.config.yaml.

xiaozhi sends the dialogue as plain text, so the model sees earlier turns in
which it "switched a light" with no visible tool call. A fast non-thinking
model sometimes copies that and answers "好了，灯关了" without calling Home
Assistant. For requests that look like device control, this provider holds
the reply back until Hermes reports a tool call (`event: hermes.tool.progress`,
which precedes any text when a tool is used). If the stream ends without one,
the reply is discarded and the request is retried once with an explicit
reminder.

Web search is slow, so the speaker says "我查一下" while it runs. Asking the
model to say that itself before calling the tool proved unreliable: it would
sometimes stop right after the filler (the turn ends in silence) or keep
talking from memory without searching. So the model now calls the tool
directly and this provider speaks the filler when Hermes reports a
web_search. A reply that merely opens with a filler is held back until it is
clear whether a search follows; a filler-only reply is retried once.

xiaozhi also sends its own ~6.5k-character system prompt, written for its
built-in tools (play_music, hass, get_weather, handle_exit_intent) and a
cached weather report that tells the model never to look weather up. With
Hermes that prompt conflicts with SOUL.md and made the model repeat a stale
"城市没找到" weather error, so only its real-time facts are forwarded.

Two more safeguards came from a scene that was "run" five times without ever
switching the lights (2026-10-11: "我回来了" -> "好，客厅灯和餐厅灯都开了"):

- A saved scene phrase is run here, without the model: the provider asks Home
  Assistant for the scene list, runs the matching script, waits until its
  devices have switched and speaks what really happened (scene_run.py).
- Whatever the request, a sentence that says a device was switched ("开了",
  "执行了", "我再打开一次") is held back until a tool that switches backs it
  up; one that states a device's state needs a Home Assistant lookup. If the
  turn ends without one, the claim is never spoken and the request is retried.

Music requests ("播放梁静茹的勇气", "放首歌", "暂停", "下一首") go to the
open-xiaoai bridge's player (`music_url`) before the model sees them, so
Hermes never tries to play music through Home Assistant. The bridge only
takes plain music phrasing and answers in a few words; everything else goes
on to Hermes as before.
"""

import json
import os
import re
import time

import httpx

from config.logger import setup_logging
from core.providers.llm.base import LLMProviderBase

try:  # home_rules' scene_run.py and ha.py, mounted next to this file.
    from . import ha as ha_client
    from . import scene_run
except ImportError:  # Loaded as a plain module (unit tests), or not mounted.
    try:
        import ha as ha_client
        import scene_run
    except ImportError:
        ha_client = scene_run = None

TAG = __name__
logger = setup_logging()

DEVICE_WORDS = re.compile(
    r"灯|风扇|空调|窗帘|电视|插座|开关|加湿器|除湿|净化器|扫地|热水器|暖气|地暖|门锁|晾衣"
    r"|冰箱|冷藏|冷冻|洗衣机|干衣机|烘干机|净水"
)
# Explicit command phrasing only: a bare 开/关 also appears in questions such as
# "空调应该开多少度" or "灯开着吗", which must be answered, not forced into a tool.
COMMAND_WORDS = re.compile(
    r"打开|关闭|关掉|关上|关了|开开|开启|启动|停止|暂停|开一下|关一下|开下|关下"
    r"|调到|调成|调为|调高|调低|调亮|调暗|调大|调小|设为|设成|设置|切换|升起|降下|开机|关机"
    r"|把.{0,10}?(开|关|调|设)"
    r"|(开|关)(灯|风扇|空调|电视|窗帘|插座)"
)
# Phrases a model uses right before it (should) look something up.
FILLERS = (
    "我查一下", "我查查", "查一下", "我搜一下", "我搜搜", "搜一下", "我看一下",
    "我看看", "我帮你查一下", "我帮你查查", "我帮你看看", "让我查一下", "让我看看",
    "稍等", "稍等一下", "等一下", "我再查一下", "我再查查", "我再看一下", "我再看看",
    "我再搜一下", "我帮你再查一下",
)
# Openings dropped when no search follows. First-person forms only, so advice
# such as "查一下体温吧" is never cut.
DROPPABLE_OPENINGS = tuple(f for f in FILLERS if not f.startswith(("查", "搜")))
LEADING_FILLER = re.compile(
    r"^\W*(?:" + "|".join(sorted(DROPPABLE_OPENINGS, key=len, reverse=True)) + ")"
)
MAX_FILLER_CLAUSE = 12
# Where the filler clause ends. \W* in LEADING_FILLER already skips emoji.
CLAUSE_END = re.compile(r"[。！？!?；;，,：:…\n]")
SEARCH_TOOLS = ("web_search", "web_extract")
FILLER_RETRY_NOTE = (
    "（系统提示：你上一次只说了一句“我查一下”就结束了，没有真正查询。"
    "需要实时信息就直接调用 web_search 搜索后回答；不需要搜索就直接回答。）"
)
# Hermes stops a turn after max_turns tool calls and its closing summary does not
# reach the stream (2026-10-22: five rules deleted one call each, then silence).
# The retry must not report the result of its own work as missing.
SILENT_AFTER_TOOLS_NOTE = (
    "（系统提示：你上一次调用了 {tools}，但没有说出回答。这些操作很可能已经完成了，不要再做一遍；"
    "需要时用查询工具看一下现在的结果，再用一句话告诉用户做了什么。）"
)
# Questions about a device's *current* state must be answered from Home
# Assistant, not from chat history or memory ("按我这边记录……").
STATE_SUBJECTS = re.compile(DEVICE_WORDS.pattern + r"|温度|湿度|漏水|水浸|窗户|门窗")
STATE_ASK = re.compile(
    r"开着|关着|亮着|灭着|开没开|关没关|是不是开|是不是关|有没有开|有没有关|几盏"
    r"|哪些.{0,4}(开|亮)|状态|现在.{0,6}(温度|湿度|多少度)|漏水"
    r"|(冰箱|冷藏|冷冻|空调).{0,8}(多少度|几度)|(洗|烘|干)(完|好)了|还(要|剩|有)多|剩多少|剩余"
)
# Preferences are answered from memory ("我睡觉空调一般开几度").
PREFERENCE_WORDS = re.compile(r"应该|习惯|一般|喜欢|平时|合适|最好|舒服|舒适|怎么设|设多少")
# The living-room TV is driven by the tv_control MCP server, never by Home Assistant
# services: its media player cannot wake it and the IR power code toggles.
TV_WORDS = re.compile(r"电视|奇异果|爱奇艺")
# What its apps leave in the chat: 小七 has no other browser or screen.
TV_APP = re.compile(r"浏览器|地址栏|网址|输入框|屏幕")
TV_TOOLS = "mcp__tv_control__"
# Follow-ups about what the TV plays name no device ("好的，暂停。", "切音量调到15。"): right
# after TV talk they are TV requests too. 2026-10-23 both were answered "已经暂停了" and
# "音量调到十五了" from the chat, with no tool call.
TV_FOLLOW_UP = re.compile(
    r"暂停|继续(?:播|放|看)|接着(?:播|放|看)|^\W*(?:好的?\W*)?继续\W*$|停止播放|下一集|上一集|第.{1,4}集"
    r"|快进|快退|倒回|音量|静音|声音(?:大|小|调)|大点声|小点声|大声点|小声点"
)
# Steps inside an app (2026-10-23 BrowseHere: "输入B点com还个网址", "打开低音搜索网站", "都不看回到"),
# but not a question about them ("那你刚刚那个K是怎么输入的呢？").
TV_APP_STEP = re.compile(r"输入|网址|网站|退出|返回|回到|主页|主界面")
WHY_HOW = re.compile(r"怎么|为什么|为啥|是不是|吗|呢\W*$")
NOT_TV = re.compile(r"音箱|小爱|歌|音乐")
# Picking a show after TV talk ("看如果奔跑是我的人生", "那我看小陈梁芳", "第二个"): 2026-10-23
# "好，我给你打开《如果奔跑是我的人生》。" came with no tool call and the TV stayed on the list.
TV_PICK = re.compile(
    r"^\W*(?:那|就|好的?|嗯)?\W*(?:我|给我)?(?:想|要|就)?(?:看|播放?|放)(?![看下来起样到见过懂清完])\w"
    r"|^\W*(?:就|要|看)?第[一二三四五六七八九十两\d]{1,2}(?:个|部)"
)
SHOW_TITLE = re.compile(r"《([^》]{1,30})》")
# A reply that lists shows to choose from ("……《理想之城》，想看哪部？", "说一个我就点开").
SHOW_CHOICE = re.compile(r"[看选播放]哪|哪[一个部]|点开")
# What TV talk leaves in the chat: the TV or iQiyi named, a show's title, an episode.
# Music talk names songs in 《》 too ("第一首是《如果你也听说》"), so those count only without it.
TV_SHOW = re.compile(SHOW_TITLE.pattern + r"|第.{1,4}集")
MUSIC_TALK = re.compile(r"歌|音乐|专辑|唱|首(?![页播])")
# A reply that does something on the TV ("我按杨超越在电视上搜了", "我这就去电视上按她的名字搜",
# "必应打开了，页面已经显示在屏幕上", "好，退出爱奇艺了"). 电视剧 is a show, not the set.
TV_SET = re.compile(r"电视(?![剧台])|奇异果|爱奇艺|" + TV_APP.pattern)


def _tv_claims(act):
    done = re.compile(
        act + r"(?:好|完|上|起来|成功)?了(?![吗么没嘛吧？?])|开始播|已(?:经)?(?:帮你|给你|为你)?" + act
        + r"|(?:打开|退出|返回|回到|输入|输好|清掉|删掉)[^，,。！!？?；;]{1,8}?了(?![吗么没嘛吧？?])")
    promise = re.compile(r"我(?:先|再|马上|这就|现在|立刻|重新|来|去|就|帮你|给你)+[^，,。！!？?]{0,12}?" + act)
    return done, promise


# Not "开播了", "热播" (the show's own news).
TV_DONE, TV_PROMISE = _tv_claims(r"(?:打开|点开|(?<![开首热直重])播放?|放|搜|换|切|暂停|继续|退出|返回|回到|输入|输好|清掉|删掉)")
# With only a show's title to go on, 搜 may be a web search ("我给你搜一下《喜剧之王》在哪拍的").
SHOW_DONE, SHOW_PROMISE = _tv_claims(r"(?:打开|点开|(?<![开首热直重])播放?|放|换|切|暂停|继续)")
TV_RETRY_NOTE = (
    "（系统提示：这是对客厅电视的请求，但你上一次没有调用电视工具就回答了。电视只能用 mcp__tv_control__ 开头的工具"
    "操作和查询（tv_power、tv_open_app、tv_play、tv_playback、tv_volume、tv_status、tv_screen、tv_click、tv_type、tv_keys），"
    "不要用 ha_call_service 或红外按钮。现在调用合适的电视工具，再按工具结果回答。）"
)
TV_CLAIM_NOTE = (
    "（系统提示：你上一次的回答说在电视上搜了、打开了或播了（或者说马上去做），但这一轮你没有调用电视工具，"
    "电视其实没有动。要操作电视，现在就调用 mcp__tv_control__ 开头的工具（播片名用 tv_play，title 填片名；"
    "输入网址或搜索词用 tv_type），按工具结果回答；只是聊天，就直接回答，不要说你操作了电视。）"
)
STATE_RETRY_NOTE = (
    "（系统提示：这是询问设备当前状态的问题，但你上一次没有查询就回答了。"
    "聊天记录和记忆里的状态可能早已过时，现在必须调用 ha_get_state 或 ha_list_entities "
    "查询后再回答。）"
)
# Questions about the past ("鱼缸灯今天亮了多久", "客厅灯几点开的", "空调昨天开了几次",
# "是谁关的灯") need the recorder history; ha_get_state only knows the present.
# Only past phrasing counts (了/过/着/的), so advice ("空调开多久合适"), what is
# left ("洗衣机还要多久") and the future ("鱼缸灯几点关") are not forced into it,
# and a trip ("去纽约要多久") has no device word at all.
HISTORY_VERB = r"(?:打开|关掉|关上|启动|运行|工作|加热|制冷|制热|开|亮|关|灭|用|洗|烘|转|跑|充|烧|扫|看|停)"
HISTORY_LENGTH = r"(?:多久|多长时间|多少时间|几个?小时|几个?钟头|几分钟|多少分钟)"
HISTORY_ASK = re.compile(
    HISTORY_VERB + r"(?:了|过|着)" + HISTORY_LENGTH
    + r"|" + HISTORY_VERB + HISTORY_LENGTH + r"了"
    + r"|" + HISTORY_VERB + r"(?:了|过)(?:几次|多少次|几回)"
    + r"|" + HISTORY_VERB + r"(?:几次|多少次|几回)了"
    + r"|(?:什么时候|啥时候|哪会儿).{0,2}" + HISTORY_VERB + r"的"
    + r"|点[^，。？！,.?!]{0,4}" + HISTORY_VERB + r"的"  # 几点开的, 三点关的, 八点二十分开的
    # "是不是你关的", but not "灯是开的还是关的" / "是不是关的" (the present state).
    + r"|是不是.{1,6}" + HISTORY_VERB + r"的"
    + r"|谁" + HISTORY_VERB + r"(?:的|了)"
    + r"|(?:用|耗)了多少.{0,2}电"
)
HISTORY_TOOLS = "mcp__home_history__"
HISTORY_RETRY_NOTE = (
    "（系统提示：这是询问设备过去情况的问题（开了多久、几点开的或关的、开过几次、谁关的），"
    "你上一次没有查询就回答了。Home Assistant 有设备的历史记录，现在必须调用 "
    "mcp__home_history__device_history 查询（period 用 today、yesterday 等），按工具算好的结果回答，"
    "不要说没有记录或查不了，也不要照搬记忆里的说法。）"
)
RETRY_NOTE = (
    "（系统提示：这是设备控制请求，但你上一次没有调用任何工具就回答了。"
    "现在必须调用 ha_call_service 真正执行，需要确认状态时调用 ha_get_state，"
    "再根据工具结果回答。不要照抄聊天记录里以前的回答。）"
)
# A command for later ("两个小时后关掉鱼缸灯", "三点关空调", "待会儿开灯") must become
# a scheduled job; RETRY_NOTE would push it to run now. "几点" is a question,
# so only concrete numbers count.
NUMBER = r"(?:\d+|[零一二两三四五六七八九十]+)"
# "调高一点", "亮一点", "有一点暗", "一点点" are amounts, not one o'clock.
AMOUNT_BEFORE = r"(?<![高低亮暗大小多少快慢强弱冷热凉暖紧松近远长短深浅早晚轻重有差再些])"
LATER_WORDS = re.compile(
    NUMBER + r"?\s*个?\s*半?\s*(?:小时|钟头|分钟)\s*(?:以?后|之后|过后)"
    r"|" + AMOUNT_BEFORE + NUMBER + r"\s*点(?![点儿])(?:半|钟|" + NUMBER + r"分?)?"
    r"|\d{1,2}\s*[:：]\s*\d{2}"
    r"|待会儿?|等会儿?|过一会儿?|一会儿(?:以?后|再)|晚一?点|定时|到点"
)
# Right after the agent confirmed a schedule ("好，十一点整关鱼缸插座"), a vague
# 开/关 with no device and no time ("会关，现在会关", said to someone else in the
# room) was taken as "switch it off now". Such a turn gets UNCLEAR_NOTE instead.
SCHEDULE_CONFIRMED = re.compile(r"(?:" + LATER_WORDS.pattern + r")[^，。？！,.?!]{0,8}(?:关|开|调)")
VAGUE_ACTION = re.compile(r"关|开(?!心|始|玩|会|学|车|门见山)|调(?!皮)")
UNCLEAR_NOTE = (
    "（系统提示：你刚安排了定时任务，这句话没说是哪个设备，也没说时间，可能是家里人之间在说话。"
    "这一轮不要调用任何工具：如果是在问你，就直接回答；听不出是不是要你现在动手，"
    "就用一句话问清楚，例如“是现在就关，还是等到点再关？”。）"
)
# Teaching a scene or linkage ("以后我说‘我回来了’就开客厅灯", "当洗衣机洗完的时候提醒我")
# mentions devices and actions, but the agent must first read the rule back and
# ask; forcing a tool call there would switch the device now instead.
RULE_WORDS = re.compile(
    r"以后.{0,4}(我|你)?.{0,2}(说|讲|喊)|每当|每次.{0,12}(就|都)|当.{1,24}(的时候|时候|时)"
    r"|如果.{1,24}(就|的话)|一.{1,12}就|场景|联动|自动化|规则|口令|每天|每晚|每周|每个?星期"
    # "漏水了马上告诉我", "洗完了提醒我"; not "告诉我书房灯开着没" (a state question).
    r"|了.{0,4}(就|马上|立刻|立即|要)?(提醒|告诉|通知)我"
)
# A reply that already answered a history question ("两小时二十八分", "开了三次").
HISTORY_FIGURES = re.compile(NUMBER + r"\s*(?:个半?|半)?\s*(?:小时|钟头|分钟?|次)")
# A command may be unclear or overheard ("会关，现在会关" said to someone else right
# after "11点关鱼缸灯"); asking back claims nothing, so it may stand without a tool.
# A question that also claims success ("好了，灯关了，还要别的吗？") may not.
QUESTION_END = re.compile(r"[？?]\s*$")
DONE_CLAIM = re.compile(r"好了|搞定|已经|已(开|关|调|设)|(开|关|调|设)(好|了)|掉了")

# After "……要我保存吗？" a "好" must reach the tool that really saves: the model
# has answered "好了，保存好了" without saving anything, and (2026-10-22) has
# called home_rule_save again, which only checks, while saying it saved.
ASKED_TO_SAVE = re.compile(r"保存吗|要我保存|存下来吗|要不要保存")
ASKED_TO_DELETE = re.compile(r"删掉吗|要我删|删除吗|要不要删")
AGREEMENT = re.compile(
    r"^(?:好的?|好啊|好吧|可以的?|可以啊|行的?|行啊|嗯+|对的?|对啊|是的?|是啊|没问题|确认|确定|要的?"
    r"|保存吧?|保存一下|存吧|存下来|删吧|删掉吧|删了吧|谢谢你?|小七)+$"
)
RULE_CONFIRM_TOOL = "mcp__home_rules__home_rule_confirm"
RULE_DELETE_TOOL = "mcp__home_rules__home_rule_delete"
SAVE_RETRY_NOTE = (
    "（系统提示：用户已经同意保存了，但你上一次没有调用 mcp__home_rules__home_rule_confirm 就回答了，"
    "其实什么都没有保存。现在调用它（不用参数），它会按原样保存刚才检查并复述过的内容，"
    "不要再调用 home_rule_save；再根据工具结果回答。）"
)
DELETE_RETRY_NOTE = (
    "（系统提示：用户已经同意删除了，但你上一次没有调用 mcp__home_rules__home_rule_delete 就回答了，"
    "其实什么都没有删除。现在只为你上一句刚问过的那一项调用它，再根据工具结果回答。）"
)
SCHEDULE_RETRY_NOTE = (
    "（系统提示：这是设备控制请求，但你上一次没有调用任何工具就回答了。"
    "用户要在之后某个时间执行的，必须调用 cronjob_manage 创建一次性定时任务"
    "（action 为 create，schedule 用 in 2h 这样的时长或带日期的时间，"
    "prompt 写明调用 ha_call_service 对哪个实体做什么，deliver 为 local），不要现在就执行；"
    "用户要现在执行的，调用 ha_call_service。再根据工具结果回答。）"
)


# What a reply claims (see the module docstring). Tools that switch something,
# or report the past, back up "开了"; a Home Assistant lookup backs up "开着".
ACT_TOOLS = ("ha_call_service", "mcp__home_rules__", "mcp__home_history__", "mcp__tv_control__", "cronjob")
LOOK_TOOLS = ("ha_",)
CLAIM_SUBJECT = re.compile(DEVICE_WORDS.pattern + r"|场景|两盏|几盏|全屋|所有|状态")
DONE_VERB = re.compile(
    r"(?:打开|关掉|关上|关闭|开启|启动|停止|暂停|切换|开|(?<!开)关|亮|灭|调好|设好)(?:好|完|上|掉|起来|成功)?了(?![吗么没嘛吧？?])"
    r"|(?:调|设|开)到[^，,。！!？?；;]{1,8}?了(?![吗么没嘛吧？?])"
    r"|已(?:经)?(?:帮你|给你|为你)?(?:打开|关掉|关上|关闭|开启|启动|开|关|调|设)"
    r"|(?:打开|关闭|关掉|开启|开|关)成功|搞定"
)
# Command execution needs no device word: "执行了", "指令发出去了", "我再执行一次".
EXEC_DONE = re.compile(
    r"执行(?:好|完|成功)?了(?![吗么没嘛吧？?])|已(?:经)?执行|(?:指令|命令)[^，,。！!？?]{0,6}(?:发|送)"
    r"|发(?:出去|过去|送)了(?![吗么没嘛吧？?])"
)
EXEC_PROMISE = re.compile(
    r"(?:再|重新)(?:发|执行)(?:一次|一遍)?|重开一次|重发一次"
    r"|我[^，,。！!？?]{0,4}?(?:再|重新)(?:打开|开|关闭|关)(?:一次|一遍)"
)
PROMISE_ACT = re.compile(r"我(?:先|再|马上|这就|现在|立刻|重新|来|帮你|给你|单独)+(?:打开|开|关|调|设|重开)(?!不)")
PROMISE_LOOK = re.compile(r"我(?:先|再|来)?(?:老老实实|仔细)?地?(?:查|看|确认)(?![不了过])")
STATE_CLAIM = re.compile(
    r"显示|状态[^，,。！!？?]{0,6}?(?:是|为)"
    r"|(?:现在|目前|都|确实|还(?!是))+是?(?:开|关|亮|灭)(?:着|的)?(?![心始玩会学车门系])"
    # "客厅灯开着呢", but not "开着还是关着" or "空调开着睡觉".
    r"|(?<!还是)(?<!或者)(?:开|关|亮|灭)着(?:呢|的|啦|哦)?(?=[，,。！!？?]|$)"
)
NEGATED = re.compile(r"没|未|不|别")  # in the three characters before a claim
# Not claims: advice ("记得把灯关了", "重发一次就好"), offers ("要不要我帮你关"), a
# rule read back ("以后你说……我就开灯", "门一开就提醒你"), the past retold
# ("刚才开了客厅灯", "今天开了两小时", "我说现在各屋灯都是关的").
INSTRUCTION = re.compile(r"(?:^|[，,]|记得|别忘了?|(?<![帮给为替])你|请|先|该|要)把|建议|最好|可以|需要")
ADVICE = re.compile(r"比较好|更好|最好|为好|建议|吧$")
# "重发一次就好" advises; "灯亮了就好" still says the light is on.
ENOUGH = re.compile(r"就好|就行|就可以")
OFFER = re.compile(r"要不要|要我|需要我|用不用")
CONDITIONAL = re.compile(r"以后|的时候|每次|每当|如果|要是|一(?![次遍下])[^，,。！!？?]{1,8}?就")
PAST = re.compile(r"刚才|刚刚|之前|上次|昨天|前天|那会儿|那时候|当时|早前|先前|我说|你说|小时|分钟|多久")
CLAUSE_EDGE = re.compile(r"[，,。！!？?；;：:\n]")
# A clause without these can be spoken before its sentence ends, unless it is
# as short as "好，", which would be left dangling when the rest is a claim.
ACTION_HINT = re.compile(r"[开关调设亮灭执发查看显状存建]|搞定|成功|添加")
MIN_EARLY_CLAUSE = 6
# The model's own steps, never meant for the speaker: "我先读一下家庭规则技能，找保存的场景口令。",
# "我先查看一下 home-rules 技能……", "用户已经确认，所以我先保存这条规则。" (it talks to the user as 你).
NARRATION = re.compile(
    r"(?:我先|我来|我去|先)(?:读|看|查看|读取|打开|加载|翻)[^，,。！!？?]{0,8}(?:技能|skill)"
    r"|home[-_ ]?rules|用户(?:已经|刚才|刚刚)?(?:确认|同意)了?"
)
NARRATION_HINT = re.compile(r"技能|skill|rules|用户", re.I)
CLAUSE_BREAK = re.compile(r"[，,：:、]")
SENTENCE_BREAK = re.compile(r"[。！!？?；;\n]")
# A scene or linkage said to be saved needs home_rule_confirm: home_rule_save
# only checks. Counted in a rule conversation, or when the sentence names one.
RULE_SUBJECT = re.compile(r"规则|联动|场景|口令|自动化|[一两几这那每]条")
RULE_SAVED = re.compile(
    r"(?:保存|创建|新建|添加)(?:好|完|成功)?了(?![吗么没嘛吧？?])|(?:存|建)(?:好|完|下来|下)了(?![吗么没嘛吧？?])"
    r"|已(?:经)?(?:帮你|给你|为你)?(?:保存|存好|存下|建好|创建|新建|添加)(?!的)|(?:保存|创建)(?:成功|完成|完毕)"
)
RULE_SAVE_PROMISE = re.compile(r"(?:接着|继续|再|马上|这就|现在|立刻|我来|我先|我再)(?:帮你|给你)?保存")
# "刚才已经保存好了" retells an earlier turn; a duration ("十分钟关灯那条") does not.
RECENT_PAST = re.compile(r"刚才|刚刚|之前|上次|昨天|前天|早就|早前|先前")
SAVE_CLAIM_NOTE = (
    "（系统提示：你上一次的回答说保存了（或者说接着保存），但这一轮你没有调用 "
    "mcp__home_rules__home_rule_confirm，其实什么都没有保存。用户已经同意保存的，现在调用它（不用参数），"
    "它会按原样保存刚才检查过的内容；用户还没同意的，先复述再问要不要保存。按工具结果如实回答。）"
)
CLAIM_RETRY_NOTE = (
    "（系统提示：你上一次的回答说已经操作了设备，或者说马上去操作，但这一轮你没有调用任何操作设备的工具，"
    "设备其实没有动。聊天记录里以前说的“开了”“关了”也不一定真的执行过。要操作设备，现在就调用 "
    "ha_call_service（用户说的是已保存场景的口令，就调用 mcp__home_rules__home_rule_run）；"
    "只是聊天或回答问题，就直接回答，不要说你操作了设备。）"
)
# "没开呀" right after a reply that said it was done: that reply may never have
# reached the device. Handled like a command.
NOT_DONE = re.compile(
    r"(?<![开关])没有?打?(?:开|关)(?![系心始玩会学车过])|没有?(?:亮|灭|反应|动静|执行|成功|生效)|不亮|没变"
    r"|(?<![着的])还是?(?:亮着|开着|关着|黑着|黑的)"
)
NOT_DONE_NOTE = (
    "（系统提示：用户说上一次的操作没有生效，聊天记录里说的“开了”“关了”不一定真的执行过。"
    "现在先调用 ha_get_state 查看实际状态，再调用 ha_call_service 重新执行"
    "（说的是已保存的场景就调用 mcp__home_rules__home_rule_run），按工具结果如实回答。）"
)
SCENE_DONE_NOTE = (
    "（系统提示：用户这句话开头说的是已保存场景“{scene}”的口令，系统已经执行了这个场景，"
    "并已经告诉用户：“{said}”。不要再执行这个场景，也不要重复这句话，只回应用户后面说的部分。）"
)


CONTEXT_BLOCK = re.compile(r"<context>(.*?)</context>", re.S)
# xiaozhi refreshes the time on every call; Hermes knows the date but not the
# time of day or the device's city. Its weather line is deliberately dropped.
# Device room / Reply style are per-device lines from voice_devices (xiaozhi
# server overrides); devices without an entry simply don't have them.
KEPT_CONTEXT = (
    "Current time", "Today's date", "Today's lunar date", "Device location",
    "Device room", "Reply style",
)


def slim_system_prompt(content):
    """Keep only the real-time facts of xiaozhi's system prompt (or None)."""
    match = CONTEXT_BLOCK.search(content if isinstance(content, str) else "")
    if not match:
        return None
    facts = [
        line.strip()
        for line in match.group(1).splitlines()
        if line.strip().startswith("- ")
        and line.strip()[2:].split(":", 1)[0].strip() in KEPT_CONTEXT
    ]
    return "语音设备提供的实时信息：\n" + "\n".join(facts) if facts else None


def _message_text(message):
    content = message.get("content") or ""
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    # xiaozhi wraps ASR output as {"content": ..., "language": ..., "emotion": ...}.
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "content" in data:
            return str(data["content"])
    except (TypeError, ValueError):
        pass
    return str(content)


def is_control_request(text):
    return bool(DEVICE_WORDS.search(text) and COMMAND_WORDS.search(text))


def asked_about_rule(dialogue):
    """"save" or "delete" when the assistant's last reply asked whether to, else None."""
    before = [m for m in dialogue if m.get("role") in ("user", "assistant")][:-1]
    if not before or before[-1].get("role") != "assistant":
        return None
    asked = _message_text(before[-1])
    return "save" if ASKED_TO_SAVE.search(asked) else "delete" if ASKED_TO_DELETE.search(asked) else None


def confirms_rule(dialogue, request):
    """"save" or "delete" when the user agreed to what the assistant just asked about."""
    asked = asked_about_rule(dialogue)
    return asked if asked and AGREEMENT.match(_spoken(request)) else None


def is_clarifying(reply):
    reply = reply.strip()
    return bool(QUESTION_END.search(reply)) and not DONE_CLAIM.search(reply)


def is_unclear_after_schedule(dialogue, request):
    """A vague 开/关 (no device, no time) right after the agent confirmed a schedule."""
    before = [m for m in dialogue if m.get("role") in ("user", "assistant")][:-1]
    if not before or before[-1].get("role") != "assistant":
        return False
    reply = _message_text(before[-1]).strip()
    if QUESTION_END.search(reply) or not SCHEDULE_CONFIRMED.search(reply):
        return False
    # "上午十一点关的" answering a history question also looks like a confirmed schedule.
    asked = [m for m in before if m.get("role") == "user"]
    if asked and HISTORY_ASK.search(_message_text(asked[-1])):
        return False
    return bool(
        VAGUE_ACTION.search(request)
        and not DEVICE_WORDS.search(request)
        and not is_control_request(request)
        and not LATER_WORDS.search(request)
    )


def is_rule_request(text):
    return bool(RULE_WORDS.search(text))


def is_scheduled_control(text):
    return is_control_request(text) and bool(LATER_WORDS.search(text))


def is_history_question(text):
    """A question about what a device did earlier, not also a command.

    "鱼缸灯是不是三点关掉的" contains the command word 关掉, so the history phrase is
    taken out before checking for a command: "开了多久了，关掉吧" is still a command.
    """
    if not (DEVICE_WORDS.search(text) and HISTORY_ASK.search(text)) or PREFERENCE_WORDS.search(text):
        return False
    return not is_control_request(HISTORY_ASK.sub("", text))


def is_history_follow_up(dialogue, request):
    """"我问你今天开了多久？" with the device named only in the previous question.

    Only when the previous reply gave no figures ("查不了"): repeating a history
    answer from the chat is fine, and forcing a second lookup made the model
    stumble ("亮了两次……不，就一次").
    """
    before = [m for m in dialogue if m.get("role") in ("user", "assistant")][:-1]
    users = [m for m in before if m.get("role") == "user"]
    if before and before[-1].get("role") == "assistant" and HISTORY_FIGURES.search(_message_text(before[-1])):
        return False
    return bool(
        users
        and not DEVICE_WORDS.search(request)
        and HISTORY_ASK.search(request)
        and not PREFERENCE_WORDS.search(request)
        and DEVICE_WORDS.search(_message_text(users[-1]))
    )


def is_tv_talk(text):
    return bool(TV_WORDS.search(text) or TV_APP.search(text) or (TV_SHOW.search(text) and not MUSIC_TALK.search(text)))


def after_tv_talk(dialogue):
    """Whether the latest of the last two exchanges' topics, TV or music, was the TV."""
    before = [m for m in dialogue if m.get("role") in ("user", "assistant")][:-1]
    for message in reversed(before[-4:]):
        text = _message_text(message)
        if is_tv_talk(text):
            return True
        if MUSIC_TALK.search(text):
            return False
    return False


def picks_offered_show(dialogue, request):
    """The request names a show the last reply listed ("《七时吉祥》《理想之城》，想看哪部？")."""
    before = [m for m in dialogue if m.get("role") in ("user", "assistant")][:-1]
    if not before or before[-1].get("role") != "assistant" or not SHOW_CHOICE.search(_message_text(before[-1])):
        return False
    spoken = _spoken(request)
    titles = (_spoken(title) for title in SHOW_TITLE.findall(_message_text(before[-1])))
    return any(len(title) >= 2 and title in spoken for title in titles)


def is_tv_follow_up(dialogue, request):
    """"暂停", "音量调到15", "看如果奔跑是我的人生", "输入网址" while the last two exchanges were about the TV."""
    if NOT_TV.search(request) or not (
            TV_FOLLOW_UP.search(request) or TV_APP_STEP.search(request) and not WHY_HOW.search(request)
            or TV_PICK.search(request) or picks_offered_show(dialogue, request)):
        return False
    return after_tv_talk(dialogue)


def is_state_question(text):
    return bool(
        STATE_SUBJECTS.search(text)
        and STATE_ASK.search(text)
        and not PREFERENCE_WORDS.search(text)
        and not is_control_request(text)
    )


def _claims(pattern, text, promise=False, past=PAST):
    """A match that is not negated ("不用关了", "指令没送到"), advice, an offer, a rule or the past."""
    for found in pattern.finditer(text):
        if NEGATED.search(text[max(0, found.start() - 3):found.start()]) or re.search(r"没|未|不", found.group()):
            continue
        if INSTRUCTION.search(text[max(0, found.start() - 6):found.start()]):
            continue
        starts = [m.end() for m in CLAUSE_EDGE.finditer(text, 0, found.start())]
        stop = CLAUSE_EDGE.search(text, found.end())
        clause = text[(starts[-1] if starts else 0):(stop.start() if stop else len(text))]
        if any(p.search(clause) for p in (CONDITIONAL, ADVICE, OFFER, past)) or (promise and ENOUGH.search(clause)):
            continue
        return True
    return False


def claim_need(sentence, acted=False, looked=False, saved=False, rule_context=False, tv=False, tv_context=False):
    """"act", "look", "save" or "tv" when the sentence claims more than this turn's tools back up, else None.

    tv: a TV tool ran; tv_context: the turn is about the TV, so a show's title is the TV's too.
    """
    text = sentence.strip()
    if not text:
        return None
    # Before `acted`: home_rule_save is a home_rules tool, but it only checks.
    if not saved and (rule_context or RULE_SUBJECT.search(text)):
        if _claims(RULE_SAVED, text, past=RECENT_PAST):
            return "save"
        if not QUESTION_END.search(text) and _claims(RULE_SAVE_PROMISE, text, promise=True, past=RECENT_PAST):
            return "save"
    # A title can read as a condition: 《如果奔跑是我的人生》.
    bare = SHOW_TITLE.sub("《》", text)
    done, promise = (TV_DONE, TV_PROMISE) if TV_SET.search(text) else (SHOW_DONE, SHOW_PROMISE)
    if (not tv and not QUESTION_END.search(text)
            and (TV_SET.search(text) or tv_context and TV_SHOW.search(text) and not MUSIC_TALK.search(bare))
            and (_claims(done, bare) or _claims(promise, bare, promise=True))):
        return "tv"
    if acted:
        return None
    subject = CLAIM_SUBJECT.search(text)
    # After a lookup, "门都关好了" reports a state; "执行了" still needs a switch.
    if _claims(EXEC_DONE, text) or (subject and not looked and _claims(DONE_VERB, text)):
        return "act"
    if QUESTION_END.search(text):
        return None  # "要我再开一次吗？" offers, it claims nothing
    if _claims(EXEC_PROMISE, text, promise=True) or (subject and _claims(PROMISE_ACT, text, promise=True)):
        return "act"
    if subject and not looked and (_claims(PROMISE_LOOK, text) or _claims(STATE_CLAIM, text)):
        return "look"
    return None


def says_done(text):
    """The reply said a device was switched (whether or not it was)."""
    return any(claim_need(part) == "act" for part in re.split(r"(?<=[。！!？?；;\n])", text))


def is_not_done_complaint(dialogue, request):
    """"没开呀", "还是没有打开" right after a reply that said it was done."""
    before = [m for m in dialogue if m.get("role") in ("user", "assistant")][:-1]
    if not before or before[-1].get("role") != "assistant":
        return False
    return bool(NOT_DONE.search(request) and says_done(_message_text(before[-1])))


def _spoken(text):
    """Letters, digits and CJK only: drops punctuation, whitespace and emoji."""
    return re.sub(r"[\W_]", "", text)


CJK = re.compile(r"[\u4e00-\u9fff]")
LATIN = re.compile(r"[A-Za-z]")
LATIN_WORDS = re.compile(r"[A-Za-z]{2,}")


def _drop_english_lead_in(text):
    """Remove an English sentence before the first Chinese character.

    Given tools, the model sometimes narrates first ("I'll check the lights.");
    the speaker must not read that. Mixed Chinese sentences are kept.
    """
    first = CJK.search(text)
    if not first:
        return text
    prefix = text[: first.start()].strip()
    # A real sentence ends with punctuation; "Apple Watch S11 缺货" is kept.
    is_sentence = len(LATIN_WORDS.findall(prefix)) >= 2 and prefix[-1:] in ".!?:"
    return text[first.start():] if is_sentence else text


def is_filler_only(text):
    return _spoken(text) in {_spoken(f) for f in FILLERS}


def _could_become_filler(text):
    spoken = _spoken(text)
    return any(_spoken(f).startswith(spoken) for f in FILLERS)


# Words a music request has; only those texts are shown to the bridge.
MUSIC_HINT = re.compile(
    r"播|放|听|唱|歌|曲|音乐|暂停|停|下一首|上一首|换|切歌|继续|接着|循环|随机|关掉|关了|关闭"
    r"|专辑|有没有|几首|多少首|有.{1,16}吗"
)


class MusicShortcut:
    """Music requests, handled by the bridge's player (open-xiaoai examples/xiaozhi,
    xiaozhi/services/music): it plays the local library on the speaker."""

    def __init__(self, url, client, timeout=12.0):
        self.url = url.rstrip("/")
        self.client = client
        # Starting a song asks the speaker a couple of things over WiFi.
        self.timeout = timeout

    def handle(self, request):
        """What to say when the bridge took the request ("" for nothing), else None."""
        if not MUSIC_HINT.search(request):
            return None
        try:
            resp = self.client.post(f"{self.url}/music/command", json={"text": request}, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.bind(tag=TAG).warning(f"音乐请求没有送到桥接，交给模型: {e}")
            return None
        if not data.get("handled"):
            return None
        return str(data.get("say") or "")


class SceneShortcut:
    """Saved scene phrases, run without the model (see scene_run.py)."""

    RETRY_AFTER_S = 30

    def __init__(self, ha, replies=None, verify_s=5.0):
        self.ha = ha
        self.replies = replies if isinstance(replies, dict) else {}
        self.verify_s = verify_s
        self._scenes, self._failed_at = {}, None

    def scenes(self):
        """Read on every turn, so a scene taught a moment ago works at once;
        the last list while Home Assistant is unreachable."""
        if self._failed_at is not None and time.monotonic() - self._failed_at < self.RETRY_AFTER_S:
            return self._scenes
        try:
            self._scenes, self._failed_at = scene_run.list_scenes(self.ha), None
        except Exception as e:
            self._failed_at = time.monotonic()
            logger.bind(tag=TAG).warning(f"读取已保存的场景失败，暂时交给模型: {e}")
        return self._scenes

    def match(self, request):
        """(phrase, script entity_id, rest of the request) or None."""
        scenes = self.scenes()
        found = scene_run.match(request, scenes) if scenes else None
        return (found[0], scenes[found[0]], found[1]) if found else None

    def run(self, phrase, entity_id):
        """(result, sentence to speak)."""
        result = scene_run.run(self.ha, entity_id, verify_s=self.verify_s)
        return result, scene_run.reply(phrase, result, self.replies)


class LLMProvider(LLMProviderBase):
    def __init__(self, config):
        self.base_url = (config.get("base_url") or config.get("url") or "http://hermes:8642/v1").rstrip("/")
        self.api_key = config.get("api_key", "")
        self.model_name = config.get("model_name", "xiaoqi-home")
        self.temperature = config.get("temperature")
        self.max_tokens = config.get("max_tokens")
        self.tool_guard = str(config.get("tool_guard", True)).lower() not in ("false", "0", "no")
        self.slim_system_prompt = str(config.get("slim_system_prompt", True)).lower() not in ("false", "0", "no")
        self.search_filler = config.get("search_filler", "我查一下。")
        self.search_failed_reply = config.get("search_failed_reply", "这次没查到，你再问我一次吧。")
        # Spoken when even the retry claims a switch (or a state) that no tool backs up.
        self.claim_failed_reply = config.get("claim_failed_reply", "这次没有真正执行成功，你再说一遍吧。")
        self.state_failed_reply = config.get("state_failed_reply", "这次没查到设备现在的状态，你再问我一次吧。")
        self.save_failed_reply = config.get("save_failed_reply", "这次没有保存成功，你再说一遍吧。")
        self.scenes = None
        ha_url = config.get("ha_url") or os.environ.get("HASS_URL")
        ha_token = config.get("ha_token") or os.environ.get("HASS_TOKEN")
        if str(config.get("scene_shortcut", True)).lower() not in ("false", "0", "no") and ha_url and ha_token:
            if scene_run is None:
                logger.bind(tag=TAG).warning("没有挂载 scene_run.py 和 ha.py，场景口令仍由模型执行")
            else:
                self.scenes = SceneShortcut(
                    ha_client.HomeAssistant(ha_url, ha_token, timeout=5),
                    config.get("scene_replies"), float(config.get("scene_verify_s", 5)),
                )
        timeout = config.get("timeout") if isinstance(config.get("timeout"), dict) else {}
        self.client = httpx.Client(
            timeout=httpx.Timeout(
                connect=timeout.get("connect", 3.0),
                read=timeout.get("read", 90.0),
                write=timeout.get("write", 10.0),
                pool=timeout.get("pool", 5.0),
            )
        )
        music_url = config.get("music_url")
        self.music = MusicShortcut(music_url, self.client) if music_url else None

    def _events(self, dialogue):
        """Yield ("tool", name) and ("text", chunk) from Hermes' SSE stream."""
        body = {"model": self.model_name, "messages": dialogue, "stream": True}
        if self.temperature not in (None, ""):
            body["temperature"] = float(self.temperature)
        if self.max_tokens not in (None, ""):
            body["max_tokens"] = int(self.max_tokens)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        event = None
        with self.client.stream(
            "POST", f"{self.base_url}/chat/completions", json=body, headers=headers
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    event = None
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event = line[6:].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    return
                try:
                    data = json.loads(payload)
                except ValueError:
                    continue
                if event == "hermes.tool.progress":
                    yield "tool", data.get("tool", "")
                elif event in (None, "message"):
                    for choice in data.get("choices") or []:
                        content = (choice.get("delta") or {}).get("content")
                        if content:
                            yield "text", content

    @staticmethod
    def _clean(chunks):
        started = False
        for chunk in chunks:
            if not started:
                chunk = chunk.lstrip()
                if not chunk:
                    continue
                started = True
            yield chunk

    def _texts(self, dialogue):
        return (value for kind, value in self._events(dialogue) if kind == "text")

    def _with_search_filler(self, events, state):
        """Text of one Hermes turn, speaking our own filler when a search starts.

        state["spoken"] tells whether anything was yielded; state["held"] keeps
        a filler-looking opening that was never resolved (for the retry check);
        state["tools"] lists the tools Hermes reported.
        """
        held = ""
        deciding = True
        for kind, value in events:
            if kind == "tool":
                state.setdefault("tools", []).append(value)
                if deciding:
                    # The model's own "我查一下…" before the tool is dropped.
                    held = ""
                    deciding = False
                    if value in SEARCH_TOOLS and self.search_filler:
                        state["spoken"] = True
                        yield self.search_filler
                continue
            if not deciding:
                state["spoken"] = True
                yield value
                continue
            held += value
            if not CJK.search(held) and LATIN.search(held):
                # Possibly an English lead-in, which may arrive a letter at a
                # time ("I", "'ll check..."): wait for Chinese or a tool.
                continue
            held = _drop_english_lead_in(held)
            waiting = False
            while True:
                match = LEADING_FILLER.match(held)
                if not match:
                    waiting = _could_become_filler(held)
                    break
                clause_end = CLAUSE_END.search(held, match.end())
                if not clause_end:
                    # Still inside "我查一下（今天的新闻）" — wait, unless it is
                    # clearly a real sentence rather than a filler.
                    waiting = len(_spoken(held)) <= MAX_FILLER_CLAUSE
                    break
                if len(_spoken(held[: clause_end.start()])) > MAX_FILLER_CLAUSE:
                    break
                if not _spoken(held[clause_end.end():]):
                    waiting = True
                    break
                # It kept talking without a search: drop the fake filler clause.
                held = held[clause_end.end():]
            if waiting:
                continue
            deciding = False
            if held.strip():
                state["spoken"] = True
                yield held
            held = ""
        state["held"] = held

    def response(self, session_id, dialogue, **kwargs):
        dialogue = [dict(message) for message in dialogue]
        for message in dialogue:
            message.setdefault("content", "")
        if self.slim_system_prompt:
            slimmed = []
            for message in dialogue:
                if message.get("role") == "system":
                    content = slim_system_prompt(message["content"])
                    if content is None:
                        continue
                    message["content"] = content
                slimmed.append(message)
            dialogue = slimmed
        users = [m for m in dialogue if m.get("role") == "user"]
        request = _message_text(users[-1]) if users else ""
        sent = request  # the user text Hermes gets when a note is added

        found = self.scenes.match(request) if self.scenes and users else None
        if found:
            phrase, entity_id, rest = found
            result, said = self.scenes.run(phrase, entity_id)
            logger.bind(tag=TAG).info(f"场景口令“{phrase}”已直接执行: {said} {result}")
            yield said
            if not rest:
                return
            # "我回来了，把空调开到二十六度": the model handles the rest only.
            scene_note = SCENE_DONE_NOTE.format(scene=phrase, said=said)
            dialogue = self._with_note(dialogue, rest, scene_note)
            request, sent = rest, f"{rest}\n{scene_note}"

        said = self.music.handle(request) if self.music and users else None
        if said is not None:
            logger.bind(tag=TAG).info(f"音乐请求已由桥接处理: {request} -> {said!r}")
            if said:
                yield said
            return

        if self.tool_guard and is_unclear_after_schedule(dialogue, request):
            logger.bind(tag=TAG).warning(f"刚定好定时任务，这句没说设备和时间，只回答或反问: {request}")
            dialogue = self._with_note(dialogue, sent, UNCLEAR_NOTE)
            required = note = reason = None
        elif self.tool_guard and confirms_rule(dialogue, request) == "save":
            required, note, reason = RULE_CONFIRM_TOOL, SAVE_RETRY_NOTE, "确认保存后未调用确认保存工具"
        elif self.tool_guard and confirms_rule(dialogue, request) == "delete":
            required, note, reason = RULE_DELETE_TOOL, DELETE_RETRY_NOTE, "确认删除后未调用删除工具"
        elif self.tool_guard and is_rule_request(request):
            # Teaching or managing a scene/linkage: answered normally (see RULE_WORDS).
            required = note = reason = None
        elif self.tool_guard and (is_history_question(request) or is_history_follow_up(dialogue, request)):
            required, note, reason = HISTORY_TOOLS, HISTORY_RETRY_NOTE, "设备历史问题未查询"
        elif self.tool_guard and is_not_done_complaint(dialogue, request):
            # Looking alone is not enough: the user wants it done this time.
            required, note, reason = ACT_TOOLS, NOT_DONE_NOTE, "用户说没生效，回答未重新执行"
        elif self.tool_guard and is_scheduled_control(request):
            # Any tool satisfies it: a time-of-day mention may still mean "now".
            required, note, reason = None, SCHEDULE_RETRY_NOTE, "定时控制请求未调用工具"
        elif self.tool_guard and (TV_WORDS.search(request) and (is_control_request(request) or is_state_question(request))
                                  or is_tv_follow_up(dialogue, request)):
            # "明早七点开电视" is a TV request too; its tool is the scheduler.
            required, note, reason = (TV_TOOLS, "cronjob"), TV_RETRY_NOTE, "电视请求未调用电视工具"
        elif self.tool_guard and is_control_request(request):
            required, note, reason = None, RETRY_NOTE, "设备控制请求未调用工具"
        elif self.tool_guard and is_state_question(request):
            required, note, reason = "ha_", STATE_RETRY_NOTE, "设备状态问题未查询"
        else:
            required = note = reason = None
        # "保存好了" needs no rule word while a scene or linkage is being taught or confirmed.
        rule_context = bool(is_rule_request(request) or asked_about_rule(dialogue))
        # "好，我给你打开《X》" is a TV claim while the TV is being talked about.
        tv_context = bool(is_tv_talk(request) or TV_PICK.search(request) and not NOT_TV.search(request)
                          or after_tv_talk(dialogue))
        context = {"rule_context": rule_context, "tv_context": tv_context}
        claim = dict(context)
        if note is None:
            state = {"spoken": False, "held": "", "tools": []}
            events = self._claim_checked(self._events(dialogue), claim)
            if self.tool_guard and asked_about_rule(dialogue):
                # Not a plain yes to "要我保存吗？" ("Does.", a misheard "对"): the model
                # narrates around its tools ("我先读取家庭规则技能……", "用户已经确认，").
                events = self._after_last_tool(events)
            yield from self._clean(self._with_search_filler(events, state))
            if claim.get("need"):
                logger.bind(tag=TAG).warning(f"没有调用工具就说做了，已丢弃并重试: {request} -> {claim['held'][:60]}")
                note = {"act": CLAIM_RETRY_NOTE, "save": SAVE_CLAIM_NOTE, "tv": TV_CLAIM_NOTE}.get(
                    claim["need"], STATE_RETRY_NOTE)
                yield from self._final_attempt(self._with_note(dialogue, sent, note), context=context)
                return
            if state["spoken"]:
                return
            logger.bind(tag=TAG).warning(
                f"只回复了“{state['held'].strip()[:20]}”没有真正查询，已重试: {request} 调用过: {state['tools']}"
            )
            acting = [t for t in state["tools"] if t.startswith(ACT_TOOLS)]
            retry_note = SILENT_AFTER_TOOLS_NOTE.format(tools="、".join(dict.fromkeys(acting))) if acting else FILLER_RETRY_NOTE
            yield from self._final_attempt(self._with_note(dialogue, sent, retry_note), self.search_failed_reply,
                                           context)
            return

        # Hold the reply until the required tool runs (any tool for commands,
        # a Home Assistant tool for state questions, the history tool for the
        # past); otherwise retry once.
        state = {"used_tool": False, "held": []}

        def guarded():
            for kind, value in self._claim_checked(self._events(dialogue), claim):
                if kind == "tool":
                    if not state["used_tool"] and (required is None or value.startswith(required)):
                        state["used_tool"] = True
                        # Anything written before the tool is lead-in noise
                        # ("我查一下", "I'll check the lights."): drop it.
                        state["held"] = []
                elif state["used_tool"]:
                    yield value
                else:
                    state["held"].append(value)

        yield from self._clean(guarded())
        if state["used_tool"] and not claim.get("need"):
            return

        held = "".join(state["held"])
        if not claim.get("need") and note in (RETRY_NOTE, SCHEDULE_RETRY_NOTE, NOT_DONE_NOTE) and is_clarifying(held):
            logger.bind(tag=TAG).warning(f"{reason}，但回答是反问，保留: {request} -> {held[:60]}")
            yield from self._clean(iter([held]))
            return
        held = claim.get("held") or held
        logger.bind(tag=TAG).warning(f"{reason}，已丢弃回答并重试: {request} -> {held[:60]}")
        yield from self._final_attempt(self._with_note(dialogue, sent, note), context=context)

    @staticmethod
    def _after_last_tool(events):
        """Text written after the turn's last tool call (all of it when no tool runs)."""
        held = []
        for kind, value in events:
            if kind == "tool":
                held = []
                yield kind, value
            else:
                held.append(value)
        if held:
            yield "text", "".join(held)

    def _final_attempt(self, dialogue, silent_reply=None, context=None):
        """The one retry. A claim that still has no tool behind it is not spoken either."""
        claim, state = dict(context or {}), {"spoken": False, "held": ""}
        yield from self._clean(self._with_search_filler(self._claim_checked(self._events(dialogue), claim), state))
        if claim.get("need"):
            logger.bind(tag=TAG).warning(f"重试后仍没有调用工具就说做了: {claim['held'][:60]}")
            yield {"act": self.claim_failed_reply, "save": self.save_failed_reply, "tv": self.claim_failed_reply}.get(
                claim["need"], self.state_failed_reply)
        elif not state["spoken"] and silent_reply:
            yield silent_reply

    def _claim_checked(self, events, claim):
        """Hermes' events, minus sentences that claim more than this turn's tools did.

        Text passes a sentence at a time (a clause at a time when it has no
        device or action word). A sentence that claims a switch ("客厅灯开了",
        "我再执行一次") or a state ("显示是关着") without a tool behind it is
        held, together with everything after it, until such a tool runs; the
        held text was its lead-in and is dropped. If the turn ends first,
        claim["need"] is "act", "look", "save" or "tv" and claim["held"] what was never
        spoken. claim["rule_context"] (set by the caller) counts a bare "保存好了",
        claim["tv_context"] a show's title as the TV's.
        """
        if not self.tool_guard:
            yield from events
            return
        rule_context = claim.get("rule_context", False)
        tv_context = claim.get("tv_context", False)
        acted = looked = saved = tv = False
        pending, held, need = "", [], None
        for kind, value in events:
            if kind == "tool":
                if pending and not need:
                    need = claim_need(pending, acted, looked, saved, rule_context, tv, tv_context)
                    if need:
                        held = [pending]
                    else:
                        yield "text", pending
                    pending = ""
                acted = acted or value.startswith(ACT_TOOLS)
                looked = looked or acted or value.startswith(LOOK_TOOLS)
                saved = saved or value.startswith(RULE_CONFIRM_TOOL)
                # A scheduled job backs up "明早七点我来打开电视".
                tv = tv or value.startswith((TV_TOOLS, "cronjob"))
                promised = ""
                if need and {"save": saved, "tv": tv, "look": looked}.get(need, acted):
                    # "我先在电视上搜一下，稍等。" tells what the slow TV tool is doing: spoken
                    # once it runs. Other lead-ins are dropped.
                    said = "".join(held)
                    if need == "tv" and not _claims(TV_DONE, SHOW_TITLE.sub("《》", said)) and not claim_need(
                            said, acted, looked, saved, rule_context, tv, tv_context):
                        promised = said
                    held, need = [], None
                yield kind, value
                if promised:
                    yield "text", promised
                continue
            if need:
                held.append(value)
                continue
            pending += value
            while True:
                end = SENTENCE_BREAK.search(pending)
                clause = CLAUSE_BREAK.search(pending)
                if (clause and (not end or clause.start() < end.start())
                        and len(_spoken(pending[: clause.end()])) >= MIN_EARLY_CLAUSE
                        and not CLAIM_SUBJECT.search(pending[: clause.end()])
                        and not ACTION_HINT.search(pending[: clause.end()])
                        and not NARRATION_HINT.search(pending[: clause.end()])):
                    part, pending = pending[: clause.end()], pending[clause.end():]
                    yield "text", part
                    continue
                if not end:
                    break
                part, pending = pending[: end.end()], pending[end.end():]
                if NARRATION.search(part):
                    continue
                need = claim_need(part, acted, looked, saved, rule_context, tv, tv_context)
                if need:
                    held, pending = [part, pending], ""
                    break
                yield "text", part
        if pending and not need and not NARRATION.search(pending):
            need = claim_need(pending, acted, looked, saved, rule_context, tv, tv_context)
            if need:
                held = [pending]
            else:
                yield "text", pending
        claim["need"] = need
        claim["held"] = "".join(held) if need else ""

    @staticmethod
    def _with_note(dialogue, request, note):
        retry = [dict(message) for message in dialogue]
        last_user = max(i for i, message in enumerate(retry) if message.get("role") == "user")
        retry[last_user]["content"] = f"{request}\n{note}"
        return retry

    def response_with_functions(self, session_id, dialogue, functions=None, **kwargs):
        for token in self.response(session_id, dialogue, **kwargs):
            yield token, None
