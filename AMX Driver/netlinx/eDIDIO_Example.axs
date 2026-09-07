PROGRAM_NAME='eDIDIO_Example'

(***********************************************************
    Example NetLinx program driving an eDIDIO controller.

    Wire four touch-panel buttons to common lighting actions. Adjust the
    controller IP, panel device, and button numbers for your system.
************************************************************)

#INCLUDE 'eDIDIO'

DEFINE_DEVICE

dvTP = 10001:1:0        // touch panel (adjust to your system)

DEFINE_CONSTANT

CHAR EDIDIO_IP[] = '192.168.1.50'

// Touch-panel button addresses
INTEGER BTN_LIGHTS_ON   = 1
INTEGER BTN_LIGHTS_OFF  = 2
INTEGER BTN_SCENE_3     = 3
INTEGER BTN_COLOUR_RED  = 4
INTEGER BTN_SEQUENCE    = 5

DEFINE_START

// Open the connection on program start; the keep-alive begins automatically
// once the socket reports ONLINE (see eDIDIO.axi).
fnEdConnect(EDIDIO_IP)

DEFINE_EVENT

BUTTON_EVENT[dvTP, BTN_LIGHTS_ON]
{
    PUSH:
    {
        fnEdSetGroupLevel(1, 0, 254)     // line 1, group 0 -> full
    }
}

BUTTON_EVENT[dvTP, BTN_LIGHTS_OFF]
{
    PUSH:
    {
        fnEdSetGroupLevel(1, 0, 0)       // line 1, group 0 -> off
    }
}

BUTTON_EVENT[dvTP, BTN_SCENE_3]
{
    PUSH:
    {
        fnEdRecallScene(1, 3)            // recall scene 3 across line 1
    }
}

BUTTON_EVENT[dvTP, BTN_COLOUR_RED]
{
    PUSH:
    {
        fnEdDmxColour(2, $FF, $00, $00, 170)   // line 2 -> red, fill universe
    }
}

BUTTON_EVENT[dvTP, BTN_SEQUENCE]
{
    PUSH:
    {
        fnEdSpektraSequence(1, 0, ED_SPK_START)   // zone 1, start sequence 0
    }
}
