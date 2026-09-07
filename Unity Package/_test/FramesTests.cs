// Byte-equality tests for the C# encoder. Run: dotnet test
//
// Reference hexes captured from edidio_control_py 0.3.0 (message_id=7), the same
// oracle used by every eDIDIO encoder.

using System;
using System.Collections.Generic;
using Edidio;
using Xunit;

public class FramesTests
{
    private const int MID = 7;

    private static string Hex(byte[] b) => BitConverter.ToString(b).Replace("-", "").ToLowerInvariant();

    [Fact]
    public void ArcLevel() =>
        Assert.Equal("cd000e080792010908011005300048c801", Hex(EdidioFrames.DaliArcLevel(MID, 1, 5, 200)));

    [Fact]
    public void GroupArcLevel() =>
        Assert.Equal("cd000e0807920109080110433000488001", Hex(EdidioFrames.DaliGroupArcLevel(MID, 1, 3, 128)));

    [Fact]
    public void CommandMax() =>
        Assert.Equal("cd000d08079201080802100a28054800", Hex(EdidioFrames.DaliCommand(MID, 2, 10, EdidioFrames.DALI_MAX_LEVEL)));

    [Fact]
    public void CommandOffNamed() =>
        Assert.Equal("cd000b0807920106080128004800", Hex(EdidioFrames.DaliCommand(MID, 1, 0, "off")));

    [Fact]
    public void BroadcastScene() =>
        Assert.Equal("cd000b0807920106080110502813", Hex(EdidioFrames.DaliBroadcastScene(MID, 1, 3)));

    [Fact]
    public void SceneOnGroup() =>
        Assert.Equal("cd000b0807920106080110442813", Hex(EdidioFrames.DaliSceneOnGroup(MID, 1, 4, 3)));

    [Fact]
    public void Dmx() =>
        Assert.Equal("cd00140807a2010f08ff0110021801200a2a04ff010000",
            Hex(EdidioFrames.DmxLevel(MID, 255, 2, 1, 10, new List<int> { 255, 0, 0 })));

    [Fact]
    public void DmxFade() =>
        Assert.Equal("cd00120807a2010d1001180120012a030a141e3032",
            Hex(EdidioFrames.DmxLevel(MID, 0, 1, 1, 1, new List<int> { 10, 20, 30 }, 50)));

    [Fact]
    public void Spektra() =>
        Assert.Equal("cd000b0807da0106080110011802",
            Hex(EdidioFrames.SpektraControl(MID, EdidioFrames.SPEKTRA_SEQUENCE, 1, 2, EdidioFrames.SPEKTRA_START)));

    [Fact]
    public void SpektraStop() =>
        Assert.Equal("cd000e0807aa01090a07080d100118ff01", Hex(EdidioFrames.SpektraStop(MID, 1, 0xFF)));

    [Fact]
    public void ArcLevelClamps() =>
        Assert.Equal(Hex(EdidioFrames.DaliArcLevel(MID, 1, 5, 254)), Hex(EdidioFrames.DaliArcLevel(MID, 1, 5, 999)));

    [Fact]
    public void LineMask()
    {
        Assert.Equal(1, EdidioFrames.LineMask(1));
        Assert.Equal(8, EdidioFrames.LineMask(4));
    }

    [Fact]
    public void KeepAliveFrame() =>
        Assert.Equal("fff6", Hex(EdidioFrames.KeepAlive));
}
