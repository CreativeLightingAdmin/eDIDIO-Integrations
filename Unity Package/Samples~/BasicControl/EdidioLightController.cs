// Sample MonoBehaviour: connect to an eDIDIO controller and drive lighting from
// gameplay. Attach to a GameObject, set the Host in the Inspector, and press
// Play. The example maps keys to actions; in a real project call the same methods
// from game events (triggers, timelines, collisions, scoring, etc.).

using Edidio;
using UnityEngine;

public class EdidioLightController : MonoBehaviour
{
    [Header("Controller")]
    public string host = "192.168.1.50";
    public int port = 23;

    [Header("Target")]
    public int line = 1;
    public int address = 5;
    public int group = 0;

    private EdidioController _edidio;

    void Start()
    {
        _edidio = new EdidioController(host, port);
        try
        {
            _edidio.Connect();
            Debug.Log($"[eDIDIO] connected to {host}:{port}");
        }
        catch (System.Exception e)
        {
            Debug.LogWarning($"[eDIDIO] connect failed: {e.Message}");
        }
    }

    void Update()
    {
        if (_edidio == null || !_edidio.Connected) return;

        // Example key mappings — replace with your own game events.
        if (Input.GetKeyDown(KeyCode.Alpha1)) _edidio.On(line, address);
        if (Input.GetKeyDown(KeyCode.Alpha0)) _edidio.Off(line, address);
        if (Input.GetKeyDown(KeyCode.S)) _edidio.RecallScene(line, 3);
        if (Input.GetKeyDown(KeyCode.R)) _edidio.DmxColor(2, 255, 0, 0);
        if (Input.GetKeyDown(KeyCode.G)) _edidio.DmxColor(2, 0, 255, 0);
        if (Input.GetKeyDown(KeyCode.P)) _edidio.Spektra(1, 0);
    }

    // Call from anywhere, e.g. a UI slider's OnValueChanged (0..1):
    public void SetBrightness(float normalized)
    {
        if (_edidio != null && _edidio.Connected)
            _edidio.SetGroupLevel(line, group, Mathf.RoundToInt(Mathf.Clamp01(normalized) * 254f));
    }

    void OnDestroy()
    {
        _edidio?.Disconnect();
    }
}
