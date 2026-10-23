package com.openxiaoai.tvhelper;

import android.accessibilityservice.AccessibilityService;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.media.AudioManager;
import android.os.PowerManager;
import android.view.KeyEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Set;

/**
 * The HTTP API. Every request needs "Authorization: Bearer TOKEN".
 *
 * GET  /status                      what is in front, screen on
 * GET  /screen?limit=150            labelled items on screen, the focused one
 * POST /click  {text, index}        click the item labelled text
 * POST /type   {text, submit}       set the text of the input field; submit runs its IME action
 * POST /key    {keys: [..]}         press keys: UP DOWN LEFT RIGHT OK BACK HOME MENU VOLUME_UP SLEEP ...
 * POST /global {action}             back, home, recents, notifications
 * GET  /apps                        launcher apps: label, package
 * POST /launch {package}            open an app
 * POST /intent {action, package, component, data, extras}   start an activity
 * GET  /media                       media sessions: app, state, title, position
 * POST /media  {action, package, value, name, extras}      play, pause, toggle, stop, next,
 *              previous, seek_to/forward/rewind (value ms), custom (name, extras)
 * GET  /volume, POST /volume {level | delta | mute}
 */
final class Api implements Http.Handler {
    private final Device device;
    private final byte[] expected;

    Api(Device device, String token) {
        this.device = device;
        this.expected = ("Bearer " + token).getBytes(StandardCharsets.UTF_8);
    }

    @Override
    public Http.Response handle(Http.Request request) throws Exception {
        String given = request.headers.get("authorization");
        if (given == null || !MessageDigest.isEqual(given.getBytes(StandardCharsets.UTF_8), expected)) {
            return Http.Response.error(401, "bad token");
        }
        JSONObject body = request.body;
        switch (request.method + " " + request.path) {
            case "GET /status":
                return Http.Response.ok(status());
            case "GET /screen":
                return Http.Response.ok(Screen.dump(device.automation, intParam(request.query.get("limit"), 150)));
            case "POST /click":
                return Http.Response.ok(Screen.click(device, body.optString("text"), body.optInt("index", 0)));
            case "POST /type":
                return Http.Response.ok(Screen.type(device.automation, body.optString("text"), body.optBoolean("submit")));
            case "POST /key":
                return Http.Response.ok(keys(body));
            case "POST /global":
                return Http.Response.ok(global(body.optString("action")));
            case "GET /apps":
                return Http.Response.ok(apps());
            case "POST /launch":
                return Http.Response.ok(launch(body.optString("package")));
            case "POST /intent":
                return Http.Response.ok(intent(body));
            case "GET /media":
                return Http.Response.ok(Media.list(device.context));
            case "POST /media":
                return Http.Response.ok(Media.control(device.context, body));
            case "GET /volume":
                return Http.Response.ok(volume());
            case "POST /volume":
                return Http.Response.ok(setVolume(body));
            default:
                return Http.Response.error(404, "no such endpoint: " + request.method + " " + request.path);
        }
    }

    private static int intParam(String value, int fallback) {
        try {
            return value == null ? fallback : Integer.parseInt(value);
        } catch (NumberFormatException e) {
            return fallback;
        }
    }

    private static JSONObject error(String message) throws JSONException {
        return new JSONObject().put("ok", false).put("error", message);
    }

    private JSONObject status() throws JSONException {
        AccessibilityNodeInfo root = Screen.root(device.automation);
        return new JSONObject()
                .put("ok", true)
                .put("version", Main.VERSION)
                .put("package", root == null || root.getPackageName() == null ? "" : root.getPackageName().toString())
                .put("activity", device.activity)
                .put("screen_on", device.context.getSystemService(PowerManager.class).isInteractive());
    }

    /** Key names as in KeyEvent without KEYCODE_, plus the remote's UP DOWN LEFT RIGHT OK. */
    static int keyCode(String name) {
        String key = name.trim().toUpperCase();
        switch (key) {
            case "UP":
            case "DOWN":
            case "LEFT":
            case "RIGHT":
            case "CENTER":
                key = "DPAD_" + key;
                break;
            case "OK":
                key = "DPAD_CENTER";
                break;
            default:
                break;
        }
        return KeyEvent.keyCodeFromString("KEYCODE_" + key);
    }

    private JSONObject keys(JSONObject body) throws JSONException {
        List<String> names = new ArrayList<>();
        JSONArray list = body.optJSONArray("keys");
        if (list != null) {
            for (int i = 0; i < list.length(); i++) {
                names.add(list.getString(i));
            }
        } else if (body.has("key")) {
            for (int i = Math.max(1, Math.min(50, body.optInt("repeat", 1))); i > 0; i--) {
                names.add(body.getString("key"));
            }
        }
        if (names.isEmpty()) {
            return error("no keys");
        }
        int pressed = 0;
        for (String name : names) {
            int code = keyCode(name);
            if (code == KeyEvent.KEYCODE_UNKNOWN) {
                return error("unknown key " + name).put("pressed", pressed);
            }
            if (pressed > 0) {
                // Give the app time to move focus before the next press, as a person would.
                try {
                    Thread.sleep(body.optInt("interval_ms", 150));
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
            if (!device.pressKey(code)) {
                return error("could not press " + name).put("pressed", pressed);
            }
            pressed++;
        }
        return new JSONObject().put("ok", true).put("pressed", pressed);
    }

    private JSONObject global(String action) throws JSONException {
        int code;
        switch (action) {
            case "back":
                code = AccessibilityService.GLOBAL_ACTION_BACK;
                break;
            case "home":
                code = AccessibilityService.GLOBAL_ACTION_HOME;
                break;
            case "recents":
                code = AccessibilityService.GLOBAL_ACTION_RECENTS;
                break;
            case "notifications":
                code = AccessibilityService.GLOBAL_ACTION_NOTIFICATIONS;
                break;
            default:
                return error("unknown action " + action);
        }
        return new JSONObject().put("ok", device.automation.performGlobalAction(code));
    }

    private JSONObject apps() throws JSONException {
        PackageManager pm = device.context.getPackageManager();
        JSONArray list = new JSONArray();
        Set<String> seen = new HashSet<>();
        for (String category : new String[]{Intent.CATEGORY_LEANBACK_LAUNCHER, Intent.CATEGORY_LAUNCHER}) {
            Intent main = new Intent(Intent.ACTION_MAIN).addCategory(category);
            for (ResolveInfo info : pm.queryIntentActivities(main, 0)) {
                String pkg = info.activityInfo.packageName;
                if (seen.add(pkg)) {
                    list.put(new JSONObject().put("label", String.valueOf(info.loadLabel(pm))).put("package", pkg));
                }
            }
        }
        return new JSONObject().put("ok", true).put("apps", list);
    }

    /** Starts an activity with the am command (argv, so no quoting), which knows how to as the shell user. */
    private static JSONObject am(List<String> args) throws JSONException {
        List<String> command = new ArrayList<>(Arrays.asList("am", "start"));
        command.addAll(args);
        String output = Device.run(command, 10_000);
        if (output == null || output.contains("Error")) {
            return error(output == null ? "am start failed" : output.trim());
        }
        return new JSONObject().put("ok", true);
    }

    private JSONObject launch(String pkg) throws JSONException {
        PackageManager pm = device.context.getPackageManager();
        Intent intent = pm.getLeanbackLaunchIntentForPackage(pkg);
        if (intent == null) {
            intent = pm.getLaunchIntentForPackage(pkg);
        }
        if (intent == null || intent.getComponent() == null) {
            return error("没有这个应用：" + pkg);
        }
        return am(Arrays.asList("-n", intent.getComponent().flattenToShortString(), "-f", "0x10200000"));
    }

    private static JSONObject intent(JSONObject body) throws JSONException {
        List<String> args = new ArrayList<>();
        String[][] options = {{"action", "-a"}, {"package", "-p"}, {"component", "-n"}, {"data", "-d"}, {"type", "-t"}};
        for (String[] option : options) {
            if (body.has(option[0])) {
                args.add(option[1]);
                args.add(body.getString(option[0]));
            }
        }
        JSONObject extras = body.optJSONObject("extras");
        if (extras != null) {
            for (Iterator<String> keys = extras.keys(); keys.hasNext(); ) {
                String key = keys.next();
                Object value = extras.get(key);
                if (value instanceof JSONObject && ((JSONObject) value).has("long")) {
                    args.addAll(Arrays.asList("--el", key, String.valueOf(((JSONObject) value).getLong("long"))));
                } else if (value instanceof Boolean) {
                    args.addAll(Arrays.asList("--ez", key, value.toString()));
                } else if (value instanceof Integer) {
                    args.addAll(Arrays.asList("--ei", key, value.toString()));
                } else if (value instanceof Long) {
                    args.addAll(Arrays.asList("--el", key, value.toString()));
                } else if (value instanceof Number) {
                    args.addAll(Arrays.asList("--ef", key, value.toString()));
                } else {
                    args.addAll(Arrays.asList("--es", key, String.valueOf(value)));
                }
            }
        }
        if (args.isEmpty()) {
            return error("empty intent");
        }
        return am(args);
    }

    private JSONObject volume() throws JSONException {
        AudioManager audio = device.context.getSystemService(AudioManager.class);
        return new JSONObject()
                .put("ok", true)
                .put("level", audio.getStreamVolume(AudioManager.STREAM_MUSIC))
                .put("max", audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC))
                .put("muted", audio.isStreamMute(AudioManager.STREAM_MUSIC));
    }

    /** Sets the volume with the media command and mutes with the mute key, as the remote does. */
    private JSONObject setVolume(JSONObject body) throws JSONException {
        AudioManager audio = device.context.getSystemService(AudioManager.class);
        if (body.has("mute") && body.getBoolean("mute") != audio.isStreamMute(AudioManager.STREAM_MUSIC)) {
            device.pressKey(KeyEvent.KEYCODE_VOLUME_MUTE);
        }
        Integer level = null;
        if (body.has("level")) {
            level = body.getInt("level");
        } else if (body.has("delta")) {
            level = audio.getStreamVolume(AudioManager.STREAM_MUSIC) + body.getInt("delta");
        }
        if (level != null) {
            int max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
            String target = String.valueOf(Math.max(0, Math.min(max, level)));
            if (Device.run(Arrays.asList("cmd", "media_session", "volume", "--stream", "3", "--set", target), 5_000) == null) {
                return error("could not set the volume");
            }
        }
        return volume();
    }
}
