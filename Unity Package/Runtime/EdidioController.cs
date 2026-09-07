// eDIDIO controller connection for Unity / .NET.
//
// A lightweight TCP client that sends byte-verified eDIDIO frames with a
// background keep-alive heartbeat. Uses only System.Net.Sockets (no Unity
// dependency), so it also runs in plain .NET. High-level control methods mirror
// the other eDIDIO drivers.

using System;
using System.Collections.Generic;
using System.Net.Sockets;
using System.Threading;

namespace Edidio
{
    public class EdidioController : IDisposable
    {
        private readonly string _host;
        private readonly int _port;
        private readonly int _keepAliveMs;
        private TcpClient _client;
        private NetworkStream _stream;
        private Timer _keepAliveTimer;
        private int _messageId;
        private readonly object _sendLock = new object();

        public bool Connected { get; private set; }

        public EdidioController(string host, int port = 23, int keepAliveMs = 7000)
        {
            _host = host;
            _port = port;
            _keepAliveMs = keepAliveMs;
        }

        public void Connect()
        {
            _client = new TcpClient();
            _client.Connect(_host, _port);
            _stream = _client.GetStream();
            Connected = true;
            if (_keepAliveMs > 0)
                _keepAliveTimer = new Timer(_ => SendKeepAlive(), null, _keepAliveMs, _keepAliveMs);
        }

        public void Disconnect()
        {
            Connected = false;
            _keepAliveTimer?.Dispose();
            _keepAliveTimer = null;
            _stream?.Dispose();
            _client?.Close();
            _stream = null;
            _client = null;
        }

        public void Dispose() => Disconnect();

        private int NextId()
        {
            _messageId = (_messageId + 1) & 0xFFFFFF;
            return _messageId;
        }

        private void Send(byte[] frame)
        {
            if (!Connected || _stream == null) return;
            lock (_sendLock)
            {
                _stream.Write(frame, 0, frame.Length);
            }
        }

        private void SendKeepAlive()
        {
            try { Send(EdidioFrames.KeepAlive); }
            catch { /* heartbeat must never throw into the timer */ }
        }

        private static int LineMask(int line) => EdidioFrames.LineMask(line);

        // --- control API ---
        public void SetLevel(int line, int address, int level) =>
            Send(EdidioFrames.DaliArcLevel(NextId(), LineMask(line), address, level));

        public void SetGroupLevel(int line, int group, int level) =>
            Send(EdidioFrames.DaliGroupArcLevel(NextId(), LineMask(line), group, level));

        public void On(int line, int address) =>
            Send(EdidioFrames.DaliCommand(NextId(), LineMask(line), address, "on"));

        public void Off(int line, int address) =>
            Send(EdidioFrames.DaliCommand(NextId(), LineMask(line), address, "off"));

        public void RecallScene(int line, int scene) =>
            Send(EdidioFrames.DaliBroadcastScene(NextId(), LineMask(line), scene));

        public void RecallSceneOnGroup(int line, int group, int scene) =>
            Send(EdidioFrames.DaliSceneOnGroup(NextId(), LineMask(line), group, scene));

        public void DmxColor(int line, byte r, byte g, byte b, int fixtures = 170) =>
            Send(EdidioFrames.DmxLevel(NextId(), 0xFF, LineMask(line), 1, fixtures, new List<int> { r, g, b }));

        public void Spektra(int zone, int index = 0, int action = EdidioFrames.SPEKTRA_START) =>
            Send(EdidioFrames.SpektraControl(NextId(), EdidioFrames.SPEKTRA_SEQUENCE, zone, index, action));

        public void SpektraStop(int zone) =>
            Send(EdidioFrames.SpektraStop(NextId(), zone));
    }
}
