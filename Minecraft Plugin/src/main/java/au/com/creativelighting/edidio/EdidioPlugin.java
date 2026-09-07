package au.com.creativelighting.edidio;

import org.bukkit.ChatColor;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.PlayerDeathEvent;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.event.weather.WeatherChangeEvent;
import org.bukkit.plugin.java.JavaPlugin;

/**
 * eDIDIO Minecraft (Spigot/Paper) plugin.
 *
 * Bridges in-game events to real architectural lighting via the eDIDIO REST API
 * Gateway — a fun demo/education piece (and genuinely useful for gaming lounges,
 * streamer setups and interactive exhibits): a player joins → lights flash; a
 * thunderstorm rolls in → the room goes stormy; a player dies → red alert.
 *
 * Also adds an /edidio admin command (scene/level/color).
 */
public class EdidioPlugin extends JavaPlugin implements Listener {

    private EdidioClient client;

    @Override
    public void onEnable() {
        saveDefaultConfig();
        client = new EdidioClient(
                getConfig().getString("gatewayUrl", "http://localhost:8080"),
                getConfig().getString("apiKey", ""),
                getConfig().getString("controller", ""));
        getServer().getPluginManager().registerEvents(this, this);
        getLogger().info("eDIDIO plugin enabled -> " + getConfig().getString("gatewayUrl"));
    }

    // Run a gateway call off the main thread so it never blocks the server tick.
    private void async(Runnable r) {
        getServer().getScheduler().runTaskAsynchronously(this, r);
    }

    // --- in-game events -> lighting ---

    @EventHandler
    public void onJoin(PlayerJoinEvent e) {
        if (!getConfig().getBoolean("events.join", true)) return;
        int line = getConfig().getInt("mapping.line", 1);
        int scene = getConfig().getInt("events.joinScene", 1);
        async(() -> client.recallScene(line, scene));
    }

    @EventHandler
    public void onDeath(PlayerDeathEvent e) {
        if (!getConfig().getBoolean("events.death", true)) return;
        int line = getConfig().getInt("mapping.dmxLine", 2);
        async(() -> client.dmxColor(line, "#FF0000")); // red alert
    }

    @EventHandler
    public void onWeather(WeatherChangeEvent e) {
        if (!getConfig().getBoolean("events.weather", true)) return;
        int line = getConfig().getInt("mapping.line", 1);
        // Storm starting -> dim scene; clearing -> bright scene.
        int scene = e.toWeatherState()
                ? getConfig().getInt("events.stormScene", 3)
                : getConfig().getInt("events.clearScene", 1);
        async(() -> client.recallScene(line, scene));
    }

    // --- /edidio command ---

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (!command.getName().equalsIgnoreCase("edidio")) return false;
        if (!sender.hasPermission("edidio.control")) {
            sender.sendMessage(ChatColor.RED + "You don't have permission.");
            return true;
        }
        if (args.length == 0) {
            sender.sendMessage(ChatColor.YELLOW + "/edidio scene <0-15> | level <addr> <0-254> | color <#RRGGBB>");
            return true;
        }
        int line = getConfig().getInt("mapping.line", 1);
        try {
            switch (args[0].toLowerCase()) {
                case "scene":
                    int scene = Integer.parseInt(args[1]);
                    async(() -> client.recallScene(line, scene));
                    sender.sendMessage(ChatColor.GREEN + "Recalling scene " + scene);
                    return true;
                case "level":
                    int addr = Integer.parseInt(args[1]);
                    int level = Integer.parseInt(args[2]);
                    async(() -> client.setLevel(line, addr, level));
                    sender.sendMessage(ChatColor.GREEN + "Address " + addr + " -> " + level);
                    return true;
                case "color":
                    String hex = args[1];
                    int dmxLine = getConfig().getInt("mapping.dmxLine", 2);
                    async(() -> client.dmxColor(dmxLine, hex));
                    sender.sendMessage(ChatColor.GREEN + "Colour " + hex);
                    return true;
                default:
                    sender.sendMessage(ChatColor.RED + "Unknown subcommand.");
                    return true;
            }
        } catch (Exception ex) {
            sender.sendMessage(ChatColor.RED + "Usage error: " + ex.getMessage());
            return true;
        }
    }
}
