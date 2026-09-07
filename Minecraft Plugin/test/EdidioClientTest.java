// Standalone check of EdidioClient's request building — runs a tiny local HTTP
// server, points the client at it, and asserts each method sends the right
// endpoint + JSON body. No Bukkit / Minecraft needed.
//
//   javac -d out ../src/main/java/au/com/creativelighting/edidio/EdidioClient.java EdidioClientTest.java
//   java  -cp out EdidioClientTest

import au.com.creativelighting.edidio.EdidioClient;

import com.sun.net.httpserver.HttpServer;
import java.io.InputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

public class EdidioClientTest {

    static final List<String[]> received = new ArrayList<>(); // [path, body, apiKey]
    static int failures = 0;

    public static void main(String[] args) throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", ex -> {
            InputStream is = ex.getRequestBody();
            String body = new String(is.readAllBytes(), StandardCharsets.UTF_8);
            received.add(new String[]{ ex.getRequestURI().getPath(), body,
                    String.valueOf(ex.getRequestHeaders().getFirst("X-Api-Key")) });
            ex.sendResponseHeaders(200, -1);
            ex.close();
        });
        server.start();
        int port = server.getAddress().getPort();

        EdidioClient client = new EdidioClient("http://127.0.0.1:" + port, "secret", "192.168.1.50");

        client.recallScene(1, 3);
        check("scene path", last()[0], "/api/v1/dali/scene");
        check("scene body", last()[1], "{\"controller\":\"192.168.1.50\",\"line\":1,\"scene\":3}");
        check("api key header", last()[2], "secret");

        client.setLevel(1, 5, 200);
        check("level path", last()[0], "/api/v1/dali/level");
        check("level body", last()[1], "{\"controller\":\"192.168.1.50\",\"line\":1,\"address\":5,\"level\":200}");

        client.setGroupLevel(1, 0, 128);
        check("group path", last()[0], "/api/v1/dali/group/level");
        check("group body", last()[1], "{\"controller\":\"192.168.1.50\",\"line\":1,\"group\":0,\"level\":128}");

        client.dmxColor(2, "#FF0000");
        check("color path", last()[0], "/api/v1/dmx/color");
        check("color body", last()[1], "{\"controller\":\"192.168.1.50\",\"line\":2,\"hex\":\"#FF0000\"}");

        // No controller / no key omits them.
        EdidioClient bare = new EdidioClient("http://127.0.0.1:" + port, "", "");
        bare.recallScene(1, 3);
        check("bare body", last()[1], "{\"line\":1,\"scene\":3}");
        check("bare no key", last()[2], "null");

        server.stop(0);
        System.out.println(failures == 0 ? "\nALL PASSED" : "\nFAILURES: " + failures);
        System.exit(failures == 0 ? 0 : 1);
    }

    static String[] last() { return received.get(received.size() - 1); }

    static void check(String name, String got, String want) {
        if (got.equals(want)) {
            System.out.println("[ok]   " + name);
        } else {
            System.out.println("[FAIL] " + name + "\n  got:  " + got + "\n  want: " + want);
            failures++;
        }
    }
}
