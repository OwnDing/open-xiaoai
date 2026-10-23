package com.openxiaoai.tvhelper;

import android.accessibilityservice.AccessibilityServiceInfo;
import android.app.UiAutomation;
import android.content.ComponentName;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.HandlerThread;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import android.view.InputDevice;
import android.view.KeyCharacterMap;
import android.view.KeyEvent;
import android.view.accessibility.AccessibilityEvent;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * What the shell user can reach from app_process: a system Context for the framework services,
 * a UiAutomation (the screen's accessibility tree, key and touch injection) and shell commands.
 */
final class Device {
    static final String TAG = "TvHelper";

    final Context context;
    final UiAutomation automation;
    /** The last activity that came to the front, e.g. com.tcl.qiyiguo/com.gala.video.app.epg.HomeActivity. */
    volatile String activity = "";

    Device() throws Exception {
        context = systemContext();
        automation = connectAutomation();
        automation.setOnAccessibilityEventListener(this::onEvent);
    }

    /** ActivityThread's system context, as scrcpy gets it; needs a main Looper on this thread. */
    private static Context systemContext() throws Exception {
        Class<?> threadClass = Class.forName("android.app.ActivityThread");
        Constructor<?> constructor = threadClass.getDeclaredConstructor();
        constructor.setAccessible(true);
        Object thread = constructor.newInstance();
        Field current = threadClass.getDeclaredField("sCurrentActivityThread");
        current.setAccessible(true);
        current.set(null, thread);
        Method getSystemContext = threadClass.getDeclaredMethod("getSystemContext");
        return (Context) getSystemContext.invoke(thread);
    }

    /** A UiAutomation like the uiautomator command's, leaving other accessibility services (TCL's 小T) running. */
    private static UiAutomation connectAutomation() throws Exception {
        HandlerThread thread = new HandlerThread("tvhelper-automation");
        thread.start();
        Class<?> connectionInterface = Class.forName("android.app.IUiAutomationConnection");
        Object connection = Class.forName("android.app.UiAutomationConnection").getDeclaredConstructor().newInstance();
        Constructor<UiAutomation> constructor = UiAutomation.class.getDeclaredConstructor(Looper.class, connectionInterface);
        constructor.setAccessible(true);
        UiAutomation automation = constructor.newInstance(thread.getLooper(), connection);
        Method connect = UiAutomation.class.getDeclaredMethod("connect", int.class);
        connect.setAccessible(true);
        connect.invoke(automation, UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
        AccessibilityServiceInfo info = automation.getServiceInfo();
        info.eventTypes = AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED;
        info.flags |= AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS
                | AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS
                | AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;
        automation.setServiceInfo(info);
        return automation;
    }

    private void onEvent(AccessibilityEvent event) {
        if (event.getEventType() != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED
                || event.getPackageName() == null || event.getClassName() == null) {
            return;
        }
        // Dialogs, menus and the keyboard change windows too; only remember real activities.
        ComponentName component = new ComponentName(event.getPackageName().toString(), event.getClassName().toString());
        try {
            context.getPackageManager().getActivityInfo(component, 0);
            activity = component.flattenToShortString();
        } catch (PackageManager.NameNotFoundException ignored) {
        }
    }

    /** Presses a key like the remote does: down then up. */
    boolean pressKey(int keyCode) {
        long now = SystemClock.uptimeMillis();
        KeyEvent down = new KeyEvent(now, now, KeyEvent.ACTION_DOWN, keyCode, 0, 0,
                KeyCharacterMap.VIRTUAL_KEYBOARD, 0, 0, InputDevice.SOURCE_KEYBOARD);
        KeyEvent up = KeyEvent.changeAction(down, KeyEvent.ACTION_UP);
        return automation.injectInputEvent(down, true) && automation.injectInputEvent(up, true);
    }

    /** Runs a command (argv, no shell) and returns its output, or null when it fails or runs too long. */
    static String run(List<String> command, long timeoutMs) {
        try {
            Process process = new ProcessBuilder(command).redirectErrorStream(true).start();
            process.getOutputStream().close();
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            InputStream in = process.getInputStream();
            Thread reader = new Thread(() -> {
                byte[] buffer = new byte[4096];
                try {
                    for (int n; (n = in.read(buffer)) > 0; ) {
                        output.write(buffer, 0, n);
                    }
                } catch (Exception ignored) {
                }
            });
            reader.start();
            if (!process.waitFor(timeoutMs, TimeUnit.MILLISECONDS)) {
                process.destroy();
                return null;
            }
            reader.join(1000);
            return process.exitValue() == 0 ? output.toString(StandardCharsets.UTF_8.name()) : null;
        } catch (Exception e) {
            Log.w(TAG, "command failed: " + command, e);
            return null;
        }
    }
}
