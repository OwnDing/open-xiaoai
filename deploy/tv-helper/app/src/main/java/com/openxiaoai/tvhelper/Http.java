package com.openxiaoai.tvhelper;

import android.util.Log;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** A small HTTP/1.1 server: one JSON request and one JSON reply per connection. */
final class Http {
    private static final String TAG = "TvHelper";
    private static final int MAX_BODY = 64 * 1024;

    interface Handler {
        Response handle(Request request) throws Exception;
    }

    static final class Request {
        final String method;
        final String path;
        final Map<String, String> query;
        final Map<String, String> headers;
        final JSONObject body;

        Request(String method, String path, Map<String, String> query, Map<String, String> headers, JSONObject body) {
            this.method = method;
            this.path = path;
            this.query = query;
            this.headers = headers;
            this.body = body;
        }
    }

    static final class Response {
        final int status;
        final JSONObject body;

        Response(int status, JSONObject body) {
            this.status = status;
            this.body = body;
        }

        static Response ok(JSONObject body) {
            return new Response(200, body);
        }

        static Response error(int status, String message) {
            JSONObject body = new JSONObject();
            try {
                body.put("ok", false).put("error", message);
            } catch (JSONException ignored) {
            }
            return new Response(status, body);
        }
    }

    private final int port;
    private final Handler handler;
    private final ExecutorService workers = Executors.newFixedThreadPool(3);
    private volatile ServerSocket server;

    Http(int port, Handler handler) {
        this.port = port;
        this.handler = handler;
    }

    void start() throws IOException {
        ServerSocket socket = new ServerSocket();
        socket.setReuseAddress(true);
        socket.bind(new InetSocketAddress(port));
        server = socket;
        Thread accept = new Thread(this::acceptLoop, "tvhelper-http");
        accept.setDaemon(true);
        accept.start();
        Log.i(TAG, "listening on " + port);
    }

    void stop() {
        ServerSocket socket = server;
        server = null;
        if (socket != null) {
            try {
                socket.close();
            } catch (IOException ignored) {
            }
        }
        workers.shutdownNow();
    }

    private void acceptLoop() {
        while (true) {
            ServerSocket socket = server;
            if (socket == null) {
                return;
            }
            try {
                Socket client = socket.accept();
                workers.execute(() -> serve(client));
            } catch (IOException e) {
                if (server != null) {
                    Log.w(TAG, "accept failed", e);
                }
            } catch (RuntimeException e) {
                // The pool was shut down while a connection came in.
                return;
            }
        }
    }

    private void serve(Socket client) {
        try (Socket socket = client) {
            socket.setSoTimeout(10_000);
            Response response;
            try {
                Request request = read(socket.getInputStream());
                response = request == null ? Response.error(400, "bad request") : handler.handle(request);
            } catch (Exception e) {
                Log.w(TAG, "request failed", e);
                response = Response.error(500, e.toString());
            }
            write(socket.getOutputStream(), response);
        } catch (IOException e) {
            Log.w(TAG, "connection failed", e);
        }
    }

    private static Request read(InputStream in) throws IOException, JSONException {
        String requestLine = readLine(in);
        if (requestLine == null) {
            return null;
        }
        String[] parts = requestLine.split(" ");
        if (parts.length < 2) {
            return null;
        }
        Map<String, String> headers = new HashMap<>();
        for (String line = readLine(in); line != null && !line.isEmpty(); line = readLine(in)) {
            int colon = line.indexOf(':');
            if (colon > 0) {
                headers.put(line.substring(0, colon).trim().toLowerCase(Locale.ROOT), line.substring(colon + 1).trim());
            }
        }
        int length = 0;
        if (headers.containsKey("content-length")) {
            length = Integer.parseInt(headers.get("content-length"));
        }
        if (length < 0 || length > MAX_BODY) {
            return null;
        }
        byte[] body = new byte[length];
        int read = 0;
        while (read < length) {
            int n = in.read(body, read, length - read);
            if (n < 0) {
                return null;
            }
            read += n;
        }
        String text = new String(body, StandardCharsets.UTF_8).trim();
        JSONObject json = text.isEmpty() ? new JSONObject() : new JSONObject(text);

        String target = parts[1];
        Map<String, String> query = new HashMap<>();
        int mark = target.indexOf('?');
        String path = mark < 0 ? target : target.substring(0, mark);
        if (mark >= 0) {
            for (String pair : target.substring(mark + 1).split("&")) {
                int eq = pair.indexOf('=');
                if (eq > 0) {
                    query.put(decode(pair.substring(0, eq)), decode(pair.substring(eq + 1)));
                } else if (!pair.isEmpty()) {
                    query.put(decode(pair), "");
                }
            }
        }
        return new Request(parts[0].toUpperCase(Locale.ROOT), path, query, headers, json);
    }

    private static String decode(String s) {
        try {
            return URLDecoder.decode(s, "UTF-8");
        } catch (Exception e) {
            return s;
        }
    }

    /** Reads one CRLF-terminated header line as ISO-8859-1, or null at end of stream. */
    private static String readLine(InputStream in) throws IOException {
        ByteArrayOutputStream line = new ByteArrayOutputStream();
        int c;
        while ((c = in.read()) >= 0) {
            if (c == '\n') {
                break;
            }
            if (c != '\r') {
                line.write(c);
            }
            if (line.size() > 8192) {
                throw new IOException("header line too long");
            }
        }
        if (c < 0 && line.size() == 0) {
            return null;
        }
        return line.toString("ISO-8859-1");
    }

    private static void write(OutputStream out, Response response) throws IOException {
        byte[] body = response.body.toString().getBytes(StandardCharsets.UTF_8);
        String head = "HTTP/1.1 " + response.status + " " + (response.status == 200 ? "OK" : "Error") + "\r\n"
                + "Content-Type: application/json; charset=utf-8\r\n"
                + "Content-Length: " + body.length + "\r\n"
                + "Connection: close\r\n\r\n";
        out.write(head.getBytes(StandardCharsets.ISO_8859_1));
        out.write(body);
        out.flush();
    }
}
