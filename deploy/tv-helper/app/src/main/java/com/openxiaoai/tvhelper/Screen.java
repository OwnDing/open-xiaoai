package com.openxiaoai.tvhelper;

import android.app.UiAutomation;
import android.graphics.Rect;
import android.os.Build;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;

/** What is on screen, and clicking or typing into it, through the accessibility tree. */
final class Screen {
    private Screen() {
    }

    /** One labelled node: its text, else its content description. */
    private static final class Item {
        final AccessibilityNodeInfo node;
        final String label;
        final Rect bounds = new Rect();
        boolean focused;
        boolean selected;
        final boolean editable;

        Item(AccessibilityNodeInfo node, String label) {
            this.node = node;
            this.label = label;
            node.getBoundsInScreen(bounds);
            focused = node.isFocused();
            selected = node.isSelected();
            editable = node.isEditable();
        }
    }

    /** The window the user is looking at: the active one, else the first app window. */
    static AccessibilityNodeInfo root(UiAutomation automation) {
        AccessibilityNodeInfo root = automation.getRootInActiveWindow();
        if (root != null) {
            return root;
        }
        for (AccessibilityWindowInfo window : automation.getWindows()) {
            if (window.getType() == AccessibilityWindowInfo.TYPE_APPLICATION && window.getRoot() != null) {
                return window.getRoot();
            }
        }
        return null;
    }

    private static String label(AccessibilityNodeInfo node) {
        CharSequence text = node.getText();
        if (text != null && text.toString().trim().length() > 0) {
            return text.toString().trim();
        }
        CharSequence desc = node.getContentDescription();
        return desc == null ? "" : desc.toString().trim();
    }

    /** The first label inside node, for focusable containers (a TV card) whose text sits in a child. */
    private static String innerLabel(AccessibilityNodeInfo node) {
        Deque<AccessibilityNodeInfo> stack = new ArrayDeque<>();
        stack.push(node);
        for (int seen = 0; !stack.isEmpty() && seen < 50; seen++) {
            AccessibilityNodeInfo next = stack.pop();
            String label = label(next);
            if (!label.isEmpty()) {
                return label;
            }
            for (int i = next.getChildCount() - 1; i >= 0; i--) {
                AccessibilityNodeInfo child = next.getChild(i);
                if (child != null) {
                    stack.push(child);
                }
            }
        }
        return "";
    }

    /** Visible labelled nodes in reading order; a child repeating its parent's label is folded into it. */
    private static List<Item> items(AccessibilityNodeInfo root) {
        List<Item> items = new ArrayList<>();
        if (root == null) {
            return items;
        }
        Deque<AccessibilityNodeInfo> stack = new ArrayDeque<>();
        stack.push(root);
        while (!stack.isEmpty()) {
            AccessibilityNodeInfo node = stack.pop();
            if (!node.isVisibleToUser()) {
                continue;
            }
            String label = label(node);
            if (label.isEmpty() && node.isFocused()) {
                label = innerLabel(node);
            }
            if (!label.isEmpty() || node.isFocused() || node.isEditable()) {
                Item item = new Item(node, label);
                Item parent = items.isEmpty() ? null : items.get(items.size() - 1);
                if (parent != null && !label.isEmpty() && parent.label.equals(label) && parent.bounds.contains(item.bounds)) {
                    parent.focused |= item.focused;
                    parent.selected |= item.selected;
                } else {
                    items.add(item);
                }
            }
            for (int i = node.getChildCount() - 1; i >= 0; i--) {
                AccessibilityNodeInfo child = node.getChild(i);
                if (child != null) {
                    stack.push(child);
                }
            }
        }
        return items;
    }

    private static JSONArray bounds(Rect r) {
        return new JSONArray().put(r.left).put(r.top).put(r.right).put(r.bottom);
    }

    static JSONObject dump(UiAutomation automation, int limit) throws JSONException {
        AccessibilityNodeInfo root = root(automation);
        JSONObject result = new JSONObject().put("ok", true);
        result.put("package", root == null || root.getPackageName() == null ? "" : root.getPackageName().toString());
        JSONArray list = new JSONArray();
        String focused = null;
        for (Item item : items(root)) {
            if (item.focused && focused == null) {
                focused = item.label;
            }
            if (list.length() >= limit) {
                continue;
            }
            JSONObject entry = new JSONObject().put("text", item.label).put("bounds", bounds(item.bounds));
            if (item.focused) {
                entry.put("focused", true);
            }
            if (item.selected) {
                entry.put("selected", true);
            }
            if (item.editable) {
                entry.put("editable", true);
            }
            list.put(entry);
        }
        result.put("focused", focused == null ? JSONObject.NULL : focused);
        result.put("items", list);
        return result;
    }

    private static String normalize(String s) {
        return s.replaceAll("[\\s\\p{Punct}·，。、：；！？“”‘’（）《》【】]", "").toLowerCase();
    }

    /** Labels matching text, best first: exact, then prefix, then substring. */
    private static List<Item> matches(List<Item> items, String text) {
        String want = normalize(text);
        List<Item> exact = new ArrayList<>();
        List<Item> prefix = new ArrayList<>();
        List<Item> contains = new ArrayList<>();
        for (Item item : items) {
            String have = normalize(item.label);
            if (have.isEmpty() || want.isEmpty()) {
                continue;
            }
            if (have.equals(want)) {
                exact.add(item);
            } else if (have.startsWith(want)) {
                prefix.add(item);
            } else if (have.contains(want)) {
                contains.add(item);
            }
        }
        exact.addAll(prefix);
        exact.addAll(contains);
        return exact;
    }

    /**
     * Clicks the index-th node labelled text. A clickable node or ancestor gets ACTION_CLICK;
     * a focusable one gets focus and an OK press, like the remote; otherwise it is tapped.
     */
    static JSONObject click(Device device, String text, int index) throws JSONException {
        List<Item> items = items(root(device.automation));
        List<Item> found = matches(items, text);
        if (index < 0 || index >= found.size()) {
            JSONArray labels = new JSONArray();
            for (Item item : items) {
                if (!item.label.isEmpty() && labels.length() < 40) {
                    labels.put(item.label);
                }
            }
            return new JSONObject().put("ok", false).put("error", "没有找到“" + text + "”").put("on_screen", labels);
        }
        Item item = found.get(index);
        JSONObject result = new JSONObject().put("ok", true).put("clicked", item.label).put("bounds", bounds(item.bounds));
        for (AccessibilityNodeInfo node = item.node; node != null; node = node.getParent()) {
            if (node.isClickable() && node.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                return result.put("method", "click");
            }
        }
        for (AccessibilityNodeInfo node = item.node; node != null; node = node.getParent()) {
            if (node.isFocusable() && (node.isFocused() || node.performAction(AccessibilityNodeInfo.ACTION_FOCUS))
                    && device.pressKey(KeyEvent.KEYCODE_DPAD_CENTER)) {
                return result.put("method", "focus_ok");
            }
        }
        if (tap(device.automation, item.bounds.exactCenterX(), item.bounds.exactCenterY())) {
            return result.put("method", "tap");
        }
        return new JSONObject().put("ok", false).put("error", "“" + item.label + "”点不了");
    }

    private static boolean tap(UiAutomation automation, float x, float y) {
        long now = SystemClock.uptimeMillis();
        MotionEvent down = MotionEvent.obtain(now, now, MotionEvent.ACTION_DOWN, x, y, 0);
        down.setSource(InputDevice.SOURCE_TOUCHSCREEN);
        MotionEvent up = MotionEvent.obtain(now, now + 60, MotionEvent.ACTION_UP, x, y, 0);
        up.setSource(InputDevice.SOURCE_TOUCHSCREEN);
        try {
            return automation.injectInputEvent(down, true) && automation.injectInputEvent(up, true);
        } finally {
            down.recycle();
            up.recycle();
        }
    }

    /**
     * Replaces the text of the focused input field (else the first one on screen); submit then
     * runs the field's IME action (search, go). Keys cannot do that: while an on-screen keyboard
     * is up, ENTER and DPAD_CENTER type its highlighted key.
     */
    static JSONObject type(UiAutomation automation, String text, boolean submit) throws JSONException {
        AccessibilityNodeInfo target = null;
        for (Item item : items(root(automation))) {
            if (item.editable && (target == null || item.focused)) {
                target = item.node;
                if (item.focused) {
                    break;
                }
            }
        }
        if (target == null) {
            return new JSONObject().put("ok", false).put("error", "屏幕上没有输入框");
        }
        Bundle args = new Bundle();
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
        if (!target.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
            return new JSONObject().put("ok", false).put("error", "输入框不接受文字");
        }
        JSONObject result = new JSONObject().put("ok", true);
        if (submit) {
            result.put("submitted", Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && target.performAction(
                    AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.getId()));
        }
        return result;
    }
}
