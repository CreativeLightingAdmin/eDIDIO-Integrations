// EdidioMod.cs — a Script Hook V .NET (SHVDN) mod that POSTs GTA V game state to
// the eDIDIO GTA V bridge, so your room lighting reacts to the game.
//
// Build: reference ScriptHookVDotNet3.dll (and System.Net.Http) in a .NET
// Framework 4.8 class library, drop the built .dll into GTA V's `scripts/` folder
// (with ScriptHookV + ScriptHookVDotNet installed). Runs in-game only.
//
// It polls the player each tick and, when the wanted level / health / vehicle
// state changes (or the player is wasted/busted), sends a small JSON POST to the
// bridge. The bridge (this repo, tested) maps it to eDIDIO lighting.

using System;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using GTA;

public class EdidioMod : Script
{
    // Point this at the bridge (server.host:port in the bridge config).
    private const string BridgeUrl = "http://127.0.0.1:3002/";
    private const string Token = ""; // set to match the bridge's server.token, if used

    private static readonly HttpClient Http = new HttpClient
    {
        Timeout = TimeSpan.FromSeconds(2)
    };

    private int _lastWanted = -1;
    private int _lastHealthBucket = -1;
    private bool _lastInVehicle;
    private bool _wasDead;
    private DateTime _nextAllowedSend = DateTime.MinValue;

    public EdidioMod()
    {
        Tick += OnTick;
        Interval = 250; // check 4x/second
    }

    private void OnTick(object sender, EventArgs e)
    {
        Ped player = Game.Player.Character;
        if (player == null) return;

        int wanted = Game.Player.WantedLevel;                 // 0-5
        int healthPct = Math.Max(0, Math.Min(100,
            (int)Math.Round(100.0 * (player.Health - 100) / Math.Max(1, player.MaxHealth - 100))));
        bool inVehicle = player.IsInVehicle();
        bool dead = player.IsDead;

        string evt = null;
        if (dead && !_wasDead)
        {
            // Rough heuristic: wanted -> busted, else wasted.
            evt = wanted > 0 ? "busted" : "wasted";
        }
        _wasDead = dead;

        int healthBucket = healthPct / 10; // only send on ~10% change to avoid spam

        bool changed = wanted != _lastWanted
                       || healthBucket != _lastHealthBucket
                       || inVehicle != _lastInVehicle
                       || evt != null;

        if (!changed) return;
        if (DateTime.UtcNow < _nextAllowedSend && evt == null) return; // light rate-limit
        _nextAllowedSend = DateTime.UtcNow.AddMilliseconds(150);

        _lastWanted = wanted;
        _lastHealthBucket = healthBucket;
        _lastInVehicle = inVehicle;

        string json = BuildJson(wanted, healthPct, inVehicle, evt);
        _ = PostAsync(json); // fire-and-forget; never block the game thread
    }

    private static string BuildJson(int wanted, int health, bool inVehicle, string evt)
    {
        var sb = new StringBuilder();
        sb.Append('{');
        if (!string.IsNullOrEmpty(Token)) sb.Append("\"token\":\"").Append(Token).Append("\",");
        sb.Append("\"wanted\":").Append(wanted).Append(',');
        sb.Append("\"health\":").Append(health).Append(',');
        sb.Append("\"in_vehicle\":").Append(inVehicle ? "true" : "false");
        if (evt != null) sb.Append(",\"event\":\"").Append(evt).Append('"');
        sb.Append('}');
        return sb.ToString();
    }

    private static async Task PostAsync(string json)
    {
        try
        {
            using (var content = new StringContent(json, Encoding.UTF8, "application/json"))
            {
                await Http.PostAsync(BridgeUrl, content).ConfigureAwait(false);
            }
        }
        catch
        {
            // Bridge offline / unreachable — ignore; the game must never stall.
        }
    }
}
