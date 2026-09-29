"""Match Xiaomi Home cloud commands to the device's own confirmation.

For gateway-relayed Mijia devices the cloud answers code 1 ("accepted") and
the device later pushes `properties_changed`. A command without that push
within 5 s most likely never reached the device, even though Home Assistant
already shows the new state.

Needs `custom_components.xiaomi_home` at debug level (logger.set_level), then:

    docker logs --tail 2000 homeassistant > ha.log 2>&1
    python ha_confirmations.py ha.log [HH:MM start, local time]
"""
import re,sys
L=open(sys.argv[1],encoding="utf-8",errors="replace").read().splitlines()
since=sys.argv[2] if len(sys.argv)>2 else "00:00"
pending=[];ok=miss=0;delays=[]
def ts(t): h,m,s=t.split(":"); return int(h)*3600+int(m)*60+float(s)
events=[]
for l in L:
    t=re.search(r"\d{4}-\d\d-\d\d (\d\d:\d\d:\d\d\.\d+)",l)
    if not t or t.group(1)<since: continue
    m=re.search(r"cloud set prop, (\d+)\.(\d+)\.(\d+), (\w+) -> .*'code': (-?\d+)",l)
    if m: events.append((ts(t.group(1)),"set",m.group(1),m.group(4),m.group(5),t.group(1)))
    m=re.search(r"properties changed, \{'did': '(\d+)', 'siid': (\d+), 'piid': (\d+), 'value': (\w+)",l)
    if m: events.append((ts(t.group(1)),"chg",m.group(1),m.group(4),"",t.group(1)))
for i,(t,k,did,val,code,raw) in enumerate(events):
    if k!="set": continue
    conf=[e for e in events[i+1:] if e[1]=="chg" and e[2]==did and e[3]==val and e[0]-t<5]
    if conf: ok+=1; delays.append(round(conf[0][0]-t,2))
    else: miss+=1; print("NO CONFIRM", raw, did, val, "code", code)
print("confirmed",ok,"missing",miss,"delays",sorted(delays))
