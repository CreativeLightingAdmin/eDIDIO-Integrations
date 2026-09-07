// Pure-C# eDIDIO protocol frame encoder — zero dependencies.
//
// Produces byte-identical output to the reference implementation
// (edidio_control_py) and the other encoders (pure-Python, NetLinx, pure-JS,
// pure-Lua), but in plain C# with no external packages — so it runs in Unity,
// .NET, Crestron SIMPL#, and any C# host.
//
// Wire format: 0xCD + 2-byte big-endian length + a serialized EdidioMessage.
// Field numbers and zero-emission rules are validated byte-for-byte in the
// bundled test project against the same 10 reference frames as every encoder.

using System;
using System.Collections.Generic;

namespace Edidio
{
    public static class EdidioFrames
    {
        // Custom DALI command enums
        public const int DALI_ARC_LEVEL = 0;
        public const int DALI_GROUP_ARC_LEVEL = 2;
        public const int DALI_BROADCAST_SCENE = 3;
        public const int DALI_SCENE_ON_GROUP = 4;

        // DALI addressing: 0-63 individual, 64-79 group (address = 64 + group), 80
        // broadcast. Scenes use the standard DALI "GO TO SCENE X" command
        // (0x10 + scene) sent to the target address.
        public const int DALI_GROUP_ADDRESS_BASE = 64;
        public const int DALI_BROADCAST_ADDRESS = 80;
        public const int DALI_GO_TO_SCENE_BASE = 0x10;

        // Standard DALI commands (subset)
        public const int DALI_OFF = 0;
        public const int DALI_FADE_UP = 1;
        public const int DALI_FADE_DOWN = 2;
        public const int DALI_STEP_UP = 3;
        public const int DALI_STEP_DOWN = 4;
        public const int DALI_MAX_LEVEL = 5;
        public const int DALI_MIN_LEVEL = 6;
        public const int DALI_RECALL_LAST = 10;
        public const int DALI_IDENTIFY = 37;

        // Spektra enums
        public const int SPEKTRA_SEQUENCE = 1;
        public const int SPEKTRA_THEME = 2;
        public const int SPEKTRA_STATIC = 3;
        public const int SPEKTRA_START = 0;
        public const int SPEKTRA_STOP = 1;
        public const int SPEKTRA_PAUSE = 2;
        public const int TRIGGER_SPEKTRA_STOP_SEQ = 13;

        public const int DALI_ARC_LEVEL_MAX = 254;

        private static readonly Dictionary<string, int> NamedCommands = new Dictionary<string, int>
        {
            { "off", DALI_OFF }, { "on", DALI_MAX_LEVEL }, { "max", DALI_MAX_LEVEL },
            { "min", DALI_MIN_LEVEL }, { "fade_up", DALI_FADE_UP }, { "fade_down", DALI_FADE_DOWN },
            { "step_up", DALI_STEP_UP }, { "step_down", DALI_STEP_DOWN },
            { "recall_last", DALI_RECALL_LAST }, { "identify", DALI_IDENTIFY }
        };

        // --- low-level protobuf wire encoding ---

        private static void WriteVarint(List<byte> outBytes, long value)
        {
            ulong v = (ulong)value;
            while (v >= 128)
            {
                outBytes.Add((byte)((v & 0x7F) | 0x80));
                v >>= 7;
            }
            outBytes.Add((byte)v);
        }

        private static void WriteTag(List<byte> outBytes, int field, int wireType)
        {
            WriteVarint(outBytes, (field << 3) | wireType);
        }

        // A varint (uint32/enum) field. Omitted when 0 unless always.
        private static void WriteUint(List<byte> outBytes, int field, long value, bool always)
        {
            if (value == 0 && !always) return;
            WriteTag(outBytes, field, 0);
            WriteVarint(outBytes, value);
        }

        // A packed repeated uint32 field.
        private static void WritePacked(List<byte> outBytes, int field, IList<int> values)
        {
            var body = new List<byte>();
            foreach (var v in values) WriteVarint(body, v);
            WriteTag(outBytes, field, 2);
            WriteVarint(outBytes, body.Count);
            outBytes.AddRange(body);
        }

        // A length-delimited embedded message field.
        private static void WriteEmbed(List<byte> outBytes, int field, List<byte> body)
        {
            WriteTag(outBytes, field, 2);
            WriteVarint(outBytes, body.Count);
            outBytes.AddRange(body);
        }

        // Wrap a serialized EdidioMessage with the 0xCD + 2-byte length header.
        private static byte[] Frame(List<byte> body)
        {
            int n = body.Count;
            var result = new byte[n + 3];
            result[0] = 0xCD;
            result[1] = (byte)((n >> 8) & 0xFF);
            result[2] = (byte)(n & 0xFF);
            body.CopyTo(result, 3);
            return result;
        }

        private static int Clamp(int v, int lo, int hi)
        {
            if (v < lo) return lo;
            if (v > hi) return hi;
            return v;
        }

        /// <summary>1-based physical line (1-4) to single-bit line mask.</summary>
        public static int LineMask(int line)
        {
            return 1 << (line - 1);
        }

        // --- message builders ---

        private static byte[] Dali(int messageId, int lineMask, int address,
            int? command, int? customCommand, int? arg)
        {
            var body = new List<byte>();
            WriteUint(body, 1, lineMask, false);
            WriteUint(body, 2, address, false);
            if (command.HasValue) WriteUint(body, 5, command.Value, true);
            if (customCommand.HasValue) WriteUint(body, 6, customCommand.Value, true);
            if (arg.HasValue) WriteUint(body, 9, arg.Value, true);

            var edidio = new List<byte>();
            WriteUint(edidio, 1, messageId, false);
            WriteEmbed(edidio, 18, body);
            return Frame(edidio);
        }

        public static byte[] DaliArcLevel(int messageId, int lineMask, int address, int level)
        {
            return Dali(messageId, lineMask, address, null, DALI_ARC_LEVEL, Clamp(level, 0, DALI_ARC_LEVEL_MAX));
        }

        public static byte[] DaliGroupArcLevel(int messageId, int lineMask, int group, int level)
        {
            // DALI_ARC_LEVEL to the group address (64 + group).
            return Dali(messageId, lineMask, DALI_GROUP_ADDRESS_BASE + group, null, DALI_ARC_LEVEL, Clamp(level, 0, DALI_ARC_LEVEL_MAX));
        }

        public static byte[] DaliCommand(int messageId, int lineMask, int address, int command, int arg = 0)
        {
            return Dali(messageId, lineMask, address, command, null, arg);
        }

        public static byte[] DaliCommand(int messageId, int lineMask, int address, string command, int arg = 0)
        {
            if (!NamedCommands.TryGetValue(command.ToLowerInvariant(), out int code))
                throw new ArgumentException("unknown DALI command: " + command);
            return Dali(messageId, lineMask, address, code, null, arg);
        }

        public static byte[] DaliBroadcastScene(int messageId, int lineMask, int scene)
        {
            // Raw "GO TO SCENE X" command (0x10 + scene) to broadcast address 80.
            return Dali(messageId, lineMask, DALI_BROADCAST_ADDRESS, DALI_GO_TO_SCENE_BASE + scene, null, null);
        }

        public static byte[] DaliSceneOnGroup(int messageId, int lineMask, int group, int scene)
        {
            // Raw "GO TO SCENE X" command (0x10 + scene) to the group address (64 + group).
            return Dali(messageId, lineMask, DALI_GROUP_ADDRESS_BASE + group, DALI_GO_TO_SCENE_BASE + scene, null, null);
        }

        public static byte[] DmxLevel(int messageId, int zone, int universeMask, int channel,
            int repeat, IList<int> levels, int fadeBy10ms = 0)
        {
            var clamped = new List<int>(levels.Count);
            foreach (var v in levels) clamped.Add(Clamp(v, 0, 255));

            var body = new List<byte>();
            WriteUint(body, 1, zone, false);
            WriteUint(body, 2, universeMask, false);
            WriteUint(body, 3, channel, false);
            WriteUint(body, 4, repeat, false);
            WritePacked(body, 5, clamped);
            WriteUint(body, 6, fadeBy10ms, false);

            var edidio = new List<byte>();
            WriteUint(edidio, 1, messageId, false);
            WriteEmbed(edidio, 20, body);
            return Frame(edidio);
        }

        public static byte[] SpektraControl(int messageId, int spektraType, int zone, int index, int action)
        {
            var body = new List<byte>();
            WriteUint(body, 1, spektraType, false);
            WriteUint(body, 2, zone, false);
            WriteUint(body, 3, index, false);
            WriteUint(body, 4, action, false);

            var edidio = new List<byte>();
            WriteUint(edidio, 1, messageId, false);
            WriteEmbed(edidio, 27, body);
            return Frame(edidio);
        }

        public static byte[] SpektraStop(int messageId, int zone, int lineMask = 0xFF)
        {
            var trigger = new List<byte>();
            WriteUint(trigger, 1, TRIGGER_SPEKTRA_STOP_SEQ, false);
            WriteUint(trigger, 2, zone, false);
            WriteUint(trigger, 3, lineMask, false);

            var external = new List<byte>();
            WriteEmbed(external, 1, trigger);

            var edidio = new List<byte>();
            WriteUint(edidio, 1, messageId, false);
            WriteEmbed(edidio, 21, external);
            return Frame(edidio);
        }

        /// <summary>Keep-alive / "Are You There" heartbeat frame.</summary>
        public static readonly byte[] KeepAlive = { 0xFF, 0xF6 };
    }
}
