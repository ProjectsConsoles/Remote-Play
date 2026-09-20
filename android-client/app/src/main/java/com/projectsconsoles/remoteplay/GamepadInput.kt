package com.projectsconsoles.remoteplay

import android.view.InputDevice
import android.view.KeyEvent
import android.view.MotionEvent

/**
 * Traduce los eventos de Android del mando (GameSir G8+ u otro, por Bluetooth o USB) al
 * [GamepadState]. Sin logica propia de red ni de pantalla, para poder usarse desde cualquier Activity.
 *
 * El G8+ en modo Android/Xbox manda: A/B/X/Y como BUTTON_A/B/X/Y, bumpers BUTTON_L1/R1, gatillos como
 * ejes LTRIGGER/RTRIGGER (a veces BRAKE/GAS, y a veces tambien como teclas BUTTON_L2/R2), stick
 * derecho en Z/RZ, cruceta como HAT_X/HAT_Y y los clicks como THUMBL/THUMBR.
 */
class GamepadInput(private val estado: GamepadState) {

    private var l2Eje = 0f
    private var r2Eje = 0f
    private var l2Tecla = 0f
    private var r2Tecla = 0f

    /** true = el evento es de un mando (o cruceta), no de un teclado ni de la pantalla. */
    fun esDeMando(fuente: Int): Boolean =
        (fuente and InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD ||
            (fuente and InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK ||
            (fuente and InputDevice.SOURCE_DPAD) == InputDevice.SOURCE_DPAD

    /** Devuelve true si el evento era del mando y ya se uso (hay que "consumirlo"). */
    fun alTecla(e: KeyEvent): Boolean {
        val bit = bitDeTecla(e.keyCode)
        val dpad = bitDeDpad(e.keyCode)
        val esGatillo = e.keyCode == KeyEvent.KEYCODE_BUTTON_L2 || e.keyCode == KeyEvent.KEYCODE_BUTTON_R2
        if (bit == 0 && dpad == 0 && !esGatillo) return false
        if (!esDeMando(e.source) && !KeyEvent.isGamepadButton(e.keyCode)) return false

        val abajo = e.action == KeyEvent.ACTION_DOWN
        when {
            bit != 0 -> estado.boton(bit, abajo)
            dpad != 0 -> estado.dpadTecla(dpad, abajo)
            e.keyCode == KeyEvent.KEYCODE_BUTTON_L2 -> { l2Tecla = if (abajo) 1f else 0f; combinarGatillos() }
            else -> { r2Tecla = if (abajo) 1f else 0f; combinarGatillos() }
        }
        return true
    }

    fun alMovimiento(e: MotionEvent): Boolean {
        if ((e.source and InputDevice.SOURCE_JOYSTICK) != InputDevice.SOURCE_JOYSTICK) return false
        if (e.action != MotionEvent.ACTION_MOVE) return false

        estado.lx = e.getAxisValue(MotionEvent.AXIS_X)
        estado.ly = e.getAxisValue(MotionEvent.AXIS_Y)

        // Stick derecho: Z/RZ en los mandos tipo Xbox; RX/RY solo si el mando no tiene Z.
        val tieneZ = e.device?.getMotionRange(MotionEvent.AXIS_Z, e.source) != null
        if (tieneZ) {
            estado.rx = e.getAxisValue(MotionEvent.AXIS_Z)
            estado.ry = e.getAxisValue(MotionEvent.AXIS_RZ)
        } else {
            estado.rx = e.getAxisValue(MotionEvent.AXIS_RX)
            estado.ry = e.getAxisValue(MotionEvent.AXIS_RY)
        }

        l2Eje = maxOf(e.getAxisValue(MotionEvent.AXIS_LTRIGGER), e.getAxisValue(MotionEvent.AXIS_BRAKE))
        r2Eje = maxOf(e.getAxisValue(MotionEvent.AXIS_RTRIGGER), e.getAxisValue(MotionEvent.AXIS_GAS))
        combinarGatillos()

        estado.hatX = e.getAxisValue(MotionEvent.AXIS_HAT_X)
        estado.hatY = e.getAxisValue(MotionEvent.AXIS_HAT_Y)
        return true
    }

    private fun combinarGatillos() {
        estado.l2 = maxOf(l2Eje, l2Tecla).coerceIn(0f, 1f)
        estado.r2 = maxOf(r2Eje, r2Tecla).coerceIn(0f, 1f)
    }

    /** Suelta todo (al perder el foco o al cerrar): que el ESP32 no se quede con un boton apretado. */
    fun soltarTodo() {
        estado.botones = 0
        estado.dpadTeclas = 0
        estado.hatX = 0f
        estado.hatY = 0f
        estado.lx = 0f
        estado.ly = 0f
        estado.rx = 0f
        estado.ry = 0f
        l2Eje = 0f; r2Eje = 0f; l2Tecla = 0f; r2Tecla = 0f
        combinarGatillos()
    }

    companion object {
        fun bitDeTecla(k: Int): Int = when (k) {
            KeyEvent.KEYCODE_BUTTON_A -> Btn.A
            KeyEvent.KEYCODE_BUTTON_B -> Btn.B
            KeyEvent.KEYCODE_BUTTON_X -> Btn.X
            KeyEvent.KEYCODE_BUTTON_Y -> Btn.Y
            KeyEvent.KEYCODE_BUTTON_L1 -> Btn.L1
            KeyEvent.KEYCODE_BUTTON_R1 -> Btn.R1
            KeyEvent.KEYCODE_BUTTON_SELECT -> Btn.SELECT
            KeyEvent.KEYCODE_BUTTON_START -> Btn.START
            KeyEvent.KEYCODE_BUTTON_MODE -> Btn.STEAM
            KeyEvent.KEYCODE_BUTTON_THUMBL -> Btn.L3
            KeyEvent.KEYCODE_BUTTON_THUMBR -> Btn.R3
            else -> 0
        }

        fun bitDeDpad(k: Int): Int = when (k) {
            KeyEvent.KEYCODE_DPAD_UP -> 1
            KeyEvent.KEYCODE_DPAD_DOWN -> 2
            KeyEvent.KEYCODE_DPAD_LEFT -> 4
            KeyEvent.KEYCODE_DPAD_RIGHT -> 8
            else -> 0
        }
    }
}
