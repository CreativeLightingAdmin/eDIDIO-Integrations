package au.com.creativelighting.edidio;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * Tiny HTTP client that posts lighting commands to the eDIDIO REST API Gateway.
 *
 * Framework-independent (no Bukkit imports) so it can be unit/compile-tested on
 * its own. Calls are fire-and-forget POSTs; run them off the main server thread.
 */
public class EdidioClient {

    private final String gatewayUrl;
    private final String apiKey;
    private final String controller;

    public EdidioClient(String gatewayUrl, String apiKey, String controller) {
        this.gatewayUrl = stripTrailingSlash(gatewayUrl == null ? "http://localhost:8080" : gatewayUrl);
        this.apiKey = apiKey;
        this.controller = controller;
    }

    private static String stripTrailingSlash(String s) {
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        return s;
    }

    private String controllerField() {
        return (controller != null && !controller.isEmpty()) ? "\"controller\":\"" + controller + "\"," : "";
    }

    /** Recall a stored scene on a line. */
    public boolean recallScene(int line, int scene) {
        return post("/api/v1/dali/scene", "{" + controllerField() + "\"line\":" + line + ",\"scene\":" + scene + "}");
    }

    /** Set a DALI address to a level (0-254). */
    public boolean setLevel(int line, int address, int level) {
        return post("/api/v1/dali/level",
                "{" + controllerField() + "\"line\":" + line + ",\"address\":" + address + ",\"level\":" + level + "}");
    }

    /** Set a DALI group to a level (0-254). */
    public boolean setGroupLevel(int line, int group, int level) {
        return post("/api/v1/dali/group/level",
                "{" + controllerField() + "\"line\":" + line + ",\"group\":" + group + ",\"level\":" + level + "}");
    }

    /** Paint a DMX line an RGB colour (e.g. "#FF0000"). */
    public boolean dmxColor(int line, String hex) {
        return post("/api/v1/dmx/color", "{" + controllerField() + "\"line\":" + line + ",\"hex\":\"" + hex + "\"}");
    }

    /** POST a JSON body to a gateway endpoint. Returns true on a 2xx response. */
    public boolean post(String endpoint, String jsonBody) {
        HttpURLConnection conn = null;
        try {
            URL url = new URL(gatewayUrl + endpoint);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setConnectTimeout(3000);
            conn.setReadTimeout(3000);
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json");
            if (apiKey != null && !apiKey.isEmpty()) {
                conn.setRequestProperty("X-API-Key", apiKey);
            }
            byte[] body = jsonBody.getBytes(StandardCharsets.UTF_8);
            try (OutputStream os = conn.getOutputStream()) {
                os.write(body);
            }
            int code = conn.getResponseCode();
            return code >= 200 && code < 300;
        } catch (Exception e) {
            return false;
        } finally {
            if (conn != null) conn.disconnect();
        }
    }
}
