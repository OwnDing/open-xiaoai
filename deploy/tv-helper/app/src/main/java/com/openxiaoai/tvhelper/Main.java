package com.openxiaoai.tvhelper;

import android.os.Looper;
import android.util.Log;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;

/**
 * 小七电视助手, run by tv-helper.sh as the adb shell user:
 * CLASSPATH=xiaoqi-tv-helper.apk app_process /system/bin --nice-name=xiaoqi-tv-helper com.openxiaoai.tvhelper.Main TOKEN_FILE
 * Serves the HTTP API on PORT until killed.
 */
public final class Main {
    static final String VERSION = "0.2.1";
    static final int PORT = 8765;

    private Main() {
    }

    public static void main(String[] args) throws Exception {
        String token = args.length > 0 ? new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8).trim() : "";
        if (token.isEmpty()) {
            System.err.println("usage: Main TOKEN_FILE (the file holds the API token)");
            System.exit(2);
        }
        Looper.prepareMainLooper();
        Device device = new Device();
        new Http(PORT, new Api(device, token)).start();
        Log.i(Device.TAG, "version " + VERSION + " listening on " + PORT);
        System.out.println("listening on " + PORT);
        Looper.loop();
    }
}
