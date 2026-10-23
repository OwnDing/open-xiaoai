package com.openxiaoai.tvhelper;

import android.content.Context;
import android.media.MediaMetadata;
import android.media.session.MediaController;
import android.media.session.MediaSessionManager;
import android.media.session.PlaybackState;
import android.os.Bundle;
import android.os.SystemClock;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.Iterator;
import java.util.List;

/** Other apps' media sessions (iQiyi's player, music apps): what is playing, and controlling it. */
final class Media {
    private Media() {
    }

    /** Needs MEDIA_CONTENT_CONTROL, which the shell user has. */
    private static List<MediaController> sessions(Context context) {
        return context.getSystemService(MediaSessionManager.class).getActiveSessions(null);
    }

    private static String stateName(int state) {
        switch (state) {
            case PlaybackState.STATE_PLAYING:
                return "playing";
            case PlaybackState.STATE_PAUSED:
                return "paused";
            case PlaybackState.STATE_STOPPED:
                return "stopped";
            case PlaybackState.STATE_BUFFERING:
            case PlaybackState.STATE_CONNECTING:
                return "buffering";
            case PlaybackState.STATE_FAST_FORWARDING:
            case PlaybackState.STATE_REWINDING:
                return "seeking";
            case PlaybackState.STATE_ERROR:
                return "error";
            default:
                return "none";
        }
    }

    /** The current position, advanced by the time played since the session last reported it. */
    private static long position(PlaybackState state) {
        long position = state.getPosition();
        if (state.getState() == PlaybackState.STATE_PLAYING && state.getLastPositionUpdateTime() > 0) {
            position += (long) ((SystemClock.elapsedRealtime() - state.getLastPositionUpdateTime()) * state.getPlaybackSpeed());
        }
        return Math.max(0, position);
    }

    private static JSONObject describe(MediaController controller) throws JSONException {
        JSONObject session = new JSONObject().put("package", controller.getPackageName());
        PlaybackState state = controller.getPlaybackState();
        session.put("state", state == null ? "none" : stateName(state.getState()));
        if (state != null) {
            session.put("position_ms", position(state));
            JSONArray custom = new JSONArray();
            for (PlaybackState.CustomAction action : state.getCustomActions()) {
                custom.put(new JSONObject().put("action", action.getAction()).put("name", String.valueOf(action.getName())));
            }
            if (custom.length() > 0) {
                session.put("custom_actions", custom);
            }
        }
        MediaMetadata metadata = controller.getMetadata();
        if (metadata != null) {
            CharSequence title = metadata.getText(MediaMetadata.METADATA_KEY_TITLE);
            if (title == null) {
                title = metadata.getText(MediaMetadata.METADATA_KEY_DISPLAY_TITLE);
            }
            CharSequence artist = metadata.getText(MediaMetadata.METADATA_KEY_ARTIST);
            CharSequence album = metadata.getText(MediaMetadata.METADATA_KEY_ALBUM);
            long duration = metadata.getLong(MediaMetadata.METADATA_KEY_DURATION);
            if (title != null) {
                session.put("title", title.toString());
            }
            if (artist != null) {
                session.put("artist", artist.toString());
            }
            if (album != null) {
                session.put("album", album.toString());
            }
            if (duration > 0) {
                session.put("duration_ms", duration);
            }
        }
        Bundle extras = controller.getExtras();
        if (extras != null && !extras.isEmpty()) {
            JSONObject values = new JSONObject();
            for (String key : extras.keySet()) {
                Object value = extras.get(key);
                if (value instanceof String || value instanceof Number || value instanceof Boolean) {
                    values.put(key, value);
                }
            }
            session.put("extras", values);
        }
        return session;
    }

    static JSONObject list(Context context) throws JSONException {
        JSONArray list = new JSONArray();
        for (MediaController controller : sessions(context)) {
            list.put(describe(controller));
        }
        return new JSONObject().put("ok", true).put("sessions", list);
    }

    /** The session of the named app, else the one playing, else the most recent one. */
    private static MediaController pick(List<MediaController> sessions, String pkg) {
        if (pkg != null && !pkg.isEmpty()) {
            for (MediaController controller : sessions) {
                if (pkg.equals(controller.getPackageName())) {
                    return controller;
                }
            }
            return null;
        }
        for (MediaController controller : sessions) {
            PlaybackState state = controller.getPlaybackState();
            if (state != null && state.getState() == PlaybackState.STATE_PLAYING) {
                return controller;
            }
        }
        return sessions.isEmpty() ? null : sessions.get(0);
    }

    /**
     * JSON to Bundle: strings, booleans, ints (whole numbers that fit), doubles; {"long": n} for a long,
     * since iQiyi reads positions with getLong and indexes with getInt.
     */
    static Bundle bundle(JSONObject json) throws JSONException {
        Bundle bundle = new Bundle();
        if (json == null) {
            return bundle;
        }
        for (Iterator<String> keys = json.keys(); keys.hasNext(); ) {
            String key = keys.next();
            Object value = json.get(key);
            if (value instanceof JSONObject && ((JSONObject) value).has("long")) {
                bundle.putLong(key, ((JSONObject) value).getLong("long"));
            } else if (value instanceof Boolean) {
                bundle.putBoolean(key, (Boolean) value);
            } else if (value instanceof Integer) {
                bundle.putInt(key, (Integer) value);
            } else if (value instanceof Long) {
                bundle.putLong(key, (Long) value);
            } else if (value instanceof Number) {
                bundle.putDouble(key, ((Number) value).doubleValue());
            } else {
                bundle.putString(key, String.valueOf(value));
            }
        }
        return bundle;
    }

    static JSONObject control(Context context, JSONObject request) throws JSONException {
        String action = request.optString("action");
        MediaController controller = pick(sessions(context), request.optString("package", null));
        if (controller == null) {
            return new JSONObject().put("ok", false).put("error", "没有正在播放的节目");
        }
        MediaController.TransportControls controls = controller.getTransportControls();
        PlaybackState state = controller.getPlaybackState();
        long value = request.optLong("value", 0);
        switch (action) {
            case "play":
                controls.play();
                break;
            case "pause":
                controls.pause();
                break;
            case "toggle":
                if (state != null && state.getState() == PlaybackState.STATE_PLAYING) {
                    controls.pause();
                } else {
                    controls.play();
                }
                break;
            case "stop":
                controls.stop();
                break;
            case "next":
                controls.skipToNext();
                break;
            case "previous":
                controls.skipToPrevious();
                break;
            case "seek_to":
                controls.seekTo(Math.max(0, value));
                break;
            case "forward":
            case "rewind":
                long now = state == null ? 0 : position(state);
                controls.seekTo(Math.max(0, now + ("forward".equals(action) ? value : -value)));
                break;
            case "custom":
                String name = request.optString("name");
                if (name.isEmpty()) {
                    return new JSONObject().put("ok", false).put("error", "custom needs name");
                }
                controls.sendCustomAction(name, bundle(request.optJSONObject("extras")));
                break;
            default:
                return new JSONObject().put("ok", false).put("error", "unknown action " + action);
        }
        return new JSONObject().put("ok", true).put("package", controller.getPackageName()).put("action", action);
    }
}
