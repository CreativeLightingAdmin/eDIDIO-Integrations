(***********************************************************
    eDIDIO.axi  -  Control Freak eDIDIO lighting control for AMX NetLinx

    Include this file in your program:  #INCLUDE 'eDIDIO'

    Builds and sends eDIDIO protobuf frames (DALI, DMX, SpektraPlus) over a
    TCP client connection, with an automatic keep-alive heartbeat.

    The frame byte-encoding below was validated byte-for-byte against the
    reference implementation (edidio_control_py) via a Python mirror of this
    exact algorithm - see netlinx/_netlinx_mirror.py and its test.

    Target: NetLinx Studio v4.
************************************************************)

DEFINE_DEVICE

dvEDIDIO = 0:3:0        // IP client virtual device (adjust port index if needed)

DEFINE_CONSTANT

INTEGER ED_TCP_PORT     = 23        // plain TCP (use 443 for TLS-capable units)
LONG    ED_KEEPALIVE_TL = 4701      // TIMELINE id for the heartbeat
LONG    ED_KEEPALIVE_MS = 7000      // heartbeat interval (ms)

// EdidioMessage field numbers
INTEGER ED_F_MSGID      = 1
INTEGER ED_F_DALI       = 18
INTEGER ED_F_DMX        = 20
INTEGER ED_F_EXTTRIG    = 21
INTEGER ED_F_SPEKTRA    = 27

// DALIMessage field numbers
INTEGER ED_D_LINEMASK   = 1
INTEGER ED_D_ADDRESS    = 2
INTEGER ED_D_COMMAND    = 5
INTEGER ED_D_CUSTOM     = 6
INTEGER ED_D_ARG        = 9

// DMXMessage field numbers
INTEGER ED_X_ZONE       = 1
INTEGER ED_X_UMASK      = 2
INTEGER ED_X_CHANNEL    = 3
INTEGER ED_X_REPEAT     = 4
INTEGER ED_X_LEVEL      = 5
INTEGER ED_X_FADE       = 6

// SpektraControlMessage field numbers
INTEGER ED_S_TYPE       = 1
INTEGER ED_S_ZONE       = 2
INTEGER ED_S_INDEX      = 3
INTEGER ED_S_ACTION     = 4

// ExternalTrigger / Trigger field numbers
INTEGER ED_E_TRIGGER    = 1
INTEGER ED_T_TYPE       = 1
INTEGER ED_T_ZONE       = 2
INTEGER ED_T_LINEMASK   = 3

// Custom DALI command enums
INTEGER ED_CUSTOM_ARC        = 0
INTEGER ED_CUSTOM_GROUP_ARC  = 2
INTEGER ED_CUSTOM_BCAST_SCN  = 3
INTEGER ED_CUSTOM_SCN_GROUP  = 4

// DALI addressing: 0-63 individual, 64-79 group (address = 64 + group), 80
// broadcast. Scenes use the standard DALI "GO TO SCENE X" command (0x10 + scene)
// sent to the target address.
INTEGER ED_DALI_GROUP_ADDR_BASE = 64
INTEGER ED_DALI_BCAST_ADDR      = 80
INTEGER ED_CMD_GO_TO_SCENE_BASE = 16

// Standard DALI command enums (subset)
INTEGER ED_CMD_OFF      = 0
INTEGER ED_CMD_MAX      = 5
INTEGER ED_CMD_MIN      = 6

// Spektra enums
INTEGER ED_SPK_SEQUENCE = 1
INTEGER ED_SPK_THEME    = 2
INTEGER ED_SPK_STATIC   = 3
INTEGER ED_SPK_START    = 0
INTEGER ED_SPK_STOP     = 1
INTEGER ED_SPK_PAUSE    = 2
INTEGER ED_TRIG_SPK_STOP= 13

CHAR ED_KEEPALIVE_FRAME[2] = {$FF, $F6}

DEFINE_VARIABLE

VOLATILE LONG    glEdMsgId
VOLATILE CHAR    gcEdIP[64]
VOLATILE INTEGER gnEdConnected

(***********************************************************
    Low-level protobuf wire encoding
    (integer-division varint; field*8 tags; n/256 length)
************************************************************)

DEFINE_FUNCTION CHAR[10] fnEdVarint(LONG lValue)
{
    STACK_VAR CHAR cOut[10]
    STACK_VAR LONG v

    v = lValue
    cOut = ''
    WHILE (v >= 128)
    {
        cOut = "cOut, ((v BAND $7F) BOR $80)"
        v = v / 128
    }
    cOut = "cOut, (v BAND $7F)"
    RETURN cOut
}

DEFINE_FUNCTION CHAR[10] fnEdTag(INTEGER nField, INTEGER nWire)
{
    RETURN fnEdVarint((nField * 8) + nWire)
}

// A varint (uint32/enum) field. Omitted when 0 unless bAlways is set.
DEFINE_FUNCTION CHAR[20] fnEdUint(INTEGER nField, LONG lValue, INTEGER bAlways)
{
    IF ((lValue = 0) AND (bAlways = 0))
    {
        RETURN ''
    }
    RETURN "fnEdTag(nField, 0), fnEdVarint(lValue)"
}

// A length-delimited embedded message field.
DEFINE_FUNCTION CHAR[400] fnEdEmbed(INTEGER nField, CHAR cBody[])
{
    RETURN "fnEdTag(nField, 2), fnEdVarint(LENGTH_STRING(cBody)), cBody"
}

// A packed repeated uint32 field (each element as a varint).
DEFINE_FUNCTION CHAR[600] fnEdPacked(INTEGER nField, CHAR cLevels[])
{
    STACK_VAR CHAR cBody[600]
    STACK_VAR INTEGER i

    cBody = ''
    FOR (i = 1; i <= LENGTH_STRING(cLevels); i++)
    {
        cBody = "cBody, fnEdVarint(cLevels[i])"
    }
    RETURN "fnEdTag(nField, 2), fnEdVarint(LENGTH_STRING(cBody)), cBody"
}

// Wrap a serialized EdidioMessage body with the 0xCD + 2-byte length header.
DEFINE_FUNCTION CHAR[700] fnEdFrame(CHAR cBody[])
{
    STACK_VAR LONG n
    n = LENGTH_STRING(cBody)
    RETURN "$CD, (n / 256), (n BAND $FF), cBody"
}

DEFINE_FUNCTION LONG fnEdNextId()
{
    glEdMsgId = (glEdMsgId + 1) BAND $FFFFFF
    RETURN glEdMsgId
}

// 1-based physical line (1-4) -> single-bit line mask.
DEFINE_FUNCTION INTEGER fnEdLineMask(INTEGER nLine)
{
    STACK_VAR INTEGER m
    STACK_VAR INTEGER i
    m = 1
    FOR (i = 1; i < nLine; i++)
    {
        m = m * 2
    }
    RETURN m
}

(***********************************************************
    Frame builders (return the full framed message)
************************************************************)

DEFINE_FUNCTION CHAR[300] fnEdBuildDali(LONG lMid, INTEGER nLineMask, INTEGER nAddress,
                                        INTEGER bHasCmd, INTEGER nCmd,
                                        INTEGER bHasCustom, INTEGER nCustom,
                                        INTEGER bHasArg, LONG lArg)
{
    STACK_VAR CHAR cBody[64]

    cBody = "fnEdUint(ED_D_LINEMASK, nLineMask, 0), fnEdUint(ED_D_ADDRESS, nAddress, 0)"
    IF (bHasCmd)
    {
        cBody = "cBody, fnEdUint(ED_D_COMMAND, nCmd, 1)"
    }
    IF (bHasCustom)
    {
        cBody = "cBody, fnEdUint(ED_D_CUSTOM, nCustom, 1)"
    }
    IF (bHasArg)
    {
        cBody = "cBody, fnEdUint(ED_D_ARG, lArg, 1)"
    }

    RETURN fnEdFrame("fnEdUint(ED_F_MSGID, lMid, 0), fnEdEmbed(ED_F_DALI, cBody)")
}

DEFINE_FUNCTION CHAR[700] fnEdBuildDmx(LONG lMid, INTEGER nZone, INTEGER nUMask,
                                       INTEGER nChannel, INTEGER nRepeat,
                                       CHAR cLevels[], LONG lFade)
{
    STACK_VAR CHAR cBody[650]

    cBody = "fnEdUint(ED_X_ZONE, nZone, 0), fnEdUint(ED_X_UMASK, nUMask, 0)"
    cBody = "cBody, fnEdUint(ED_X_CHANNEL, nChannel, 0), fnEdUint(ED_X_REPEAT, nRepeat, 0)"
    cBody = "cBody, fnEdPacked(ED_X_LEVEL, cLevels)"
    cBody = "cBody, fnEdUint(ED_X_FADE, lFade, 0)"

    RETURN fnEdFrame("fnEdUint(ED_F_MSGID, lMid, 0), fnEdEmbed(ED_F_DMX, cBody)")
}

DEFINE_FUNCTION CHAR[200] fnEdBuildSpektra(LONG lMid, INTEGER nType, INTEGER nZone,
                                           INTEGER nIndex, INTEGER nAction)
{
    STACK_VAR CHAR cBody[32]

    cBody = "fnEdUint(ED_S_TYPE, nType, 0), fnEdUint(ED_S_ZONE, nZone, 0)"
    cBody = "cBody, fnEdUint(ED_S_INDEX, nIndex, 0), fnEdUint(ED_S_ACTION, nAction, 0)"

    RETURN fnEdFrame("fnEdUint(ED_F_MSGID, lMid, 0), fnEdEmbed(ED_F_SPEKTRA, cBody)")
}

DEFINE_FUNCTION CHAR[200] fnEdBuildSpektraStop(LONG lMid, INTEGER nZone, INTEGER nLineMask)
{
    STACK_VAR CHAR cTrigger[32]

    cTrigger = "fnEdUint(ED_T_TYPE, ED_TRIG_SPK_STOP, 0), fnEdUint(ED_T_ZONE, nZone, 0)"
    cTrigger = "cTrigger, fnEdUint(ED_T_LINEMASK, nLineMask, 0)"

    RETURN fnEdFrame("fnEdUint(ED_F_MSGID, lMid, 0), fnEdEmbed(ED_F_EXTTRIG, fnEdEmbed(ED_E_TRIGGER, cTrigger))")
}

(***********************************************************
    Send helpers  -  build + transmit
************************************************************)

DEFINE_FUNCTION fnEdSend(CHAR cFrame[])
{
    IF (gnEdConnected)
    {
        SEND_STRING dvEDIDIO, cFrame
    }
}

DEFINE_FUNCTION fnEdSetLevel(INTEGER nLine, INTEGER nAddress, INTEGER nLevel)
{
    fnEdSend(fnEdBuildDali(fnEdNextId(), fnEdLineMask(nLine), nAddress, 0, 0, 1, ED_CUSTOM_ARC, 1, nLevel))
}

DEFINE_FUNCTION fnEdSetGroupLevel(INTEGER nLine, INTEGER nGroup, INTEGER nLevel)
{
    // DALI_ARC_LEVEL to the group address (64 + group).
    fnEdSend(fnEdBuildDali(fnEdNextId(), fnEdLineMask(nLine), ED_DALI_GROUP_ADDR_BASE + nGroup, 0, 0, 1, ED_CUSTOM_ARC, 1, nLevel))
}

DEFINE_FUNCTION fnEdOn(INTEGER nLine, INTEGER nAddress)
{
    fnEdSend(fnEdBuildDali(fnEdNextId(), fnEdLineMask(nLine), nAddress, 1, ED_CMD_MAX, 0, 0, 1, 0))
}

DEFINE_FUNCTION fnEdOff(INTEGER nLine, INTEGER nAddress)
{
    fnEdSend(fnEdBuildDali(fnEdNextId(), fnEdLineMask(nLine), nAddress, 1, ED_CMD_OFF, 0, 0, 1, 0))
}

DEFINE_FUNCTION fnEdRecallScene(INTEGER nLine, INTEGER nScene)
{
    // Raw "GO TO SCENE X" command (0x10 + scene) to broadcast address 80.
    fnEdSend(fnEdBuildDali(fnEdNextId(), fnEdLineMask(nLine), ED_DALI_BCAST_ADDR, 1, ED_CMD_GO_TO_SCENE_BASE + nScene, 0, 0, 0, 0))
}

DEFINE_FUNCTION fnEdRecallSceneOnGroup(INTEGER nLine, INTEGER nGroup, INTEGER nScene)
{
    // Raw "GO TO SCENE X" command (0x10 + scene) to the group address (64 + group).
    fnEdSend(fnEdBuildDali(fnEdNextId(), fnEdLineMask(nLine), ED_DALI_GROUP_ADDR_BASE + nGroup, 1, ED_CMD_GO_TO_SCENE_BASE + nScene, 0, 0, 0, 0))
}

// Paint an RGB colour across a DMX line. nFixtures = how many RGB triplets to
// tile (use 170 to fill a 512-channel universe).
DEFINE_FUNCTION fnEdDmxColour(INTEGER nLine, INTEGER nR, INTEGER nG, INTEGER nB, INTEGER nFixtures)
{
    STACK_VAR CHAR cRgb[3]
    cRgb = "nR, nG, nB"
    fnEdSend(fnEdBuildDmx(fnEdNextId(), $FF, fnEdLineMask(nLine), 1, nFixtures, cRgb, 0))
}

DEFINE_FUNCTION fnEdSpektraSequence(INTEGER nZone, INTEGER nIndex, INTEGER nAction)
{
    fnEdSend(fnEdBuildSpektra(fnEdNextId(), ED_SPK_SEQUENCE, nZone, nIndex, nAction))
}

DEFINE_FUNCTION fnEdSpektraStop(INTEGER nZone)
{
    fnEdSend(fnEdBuildSpektraStop(fnEdNextId(), nZone, $FF))
}

(***********************************************************
    Connection management
************************************************************)

DEFINE_FUNCTION fnEdConnect(CHAR cIP[])
{
    gcEdIP = cIP
    IP_CLIENT_OPEN(dvEDIDIO.PORT, gcEdIP, ED_TCP_PORT, IP_TCP)
}

DEFINE_FUNCTION fnEdDisconnect()
{
    IF (TIMELINE_ACTIVE(ED_KEEPALIVE_TL))
    {
        TIMELINE_KILL(ED_KEEPALIVE_TL)
    }
    IP_CLIENT_CLOSE(dvEDIDIO.PORT)
    gnEdConnected = 0
}

DEFINE_EVENT

DATA_EVENT[dvEDIDIO]
{
    ONLINE:
    {
        gnEdConnected = 1
        // Start the keep-alive heartbeat.
        IF (!TIMELINE_ACTIVE(ED_KEEPALIVE_TL))
        {
            TIMELINE_CREATE(ED_KEEPALIVE_TL, ED_KEEPALIVE_MS, 1, TIMELINE_RELATIVE, TIMELINE_REPEAT)
        }
    }
    OFFLINE:
    {
        gnEdConnected = 0
        IF (TIMELINE_ACTIVE(ED_KEEPALIVE_TL))
        {
            TIMELINE_KILL(ED_KEEPALIVE_TL)
        }
    }
    ONERROR:
    {
        gnEdConnected = 0
    }
    STRING:
    {
        // Responses arrive here (DATA.TEXT). Not parsed in this control-only
        // module; add handling if you need query/feedback.
    }
}

TIMELINE_EVENT[ED_KEEPALIVE_TL]
{
    IF (gnEdConnected)
    {
        SEND_STRING dvEDIDIO, ED_KEEPALIVE_FRAME
    }
}
