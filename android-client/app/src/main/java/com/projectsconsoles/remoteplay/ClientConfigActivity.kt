package com.projectsconsoles.remoteplay

import android.os.Bundle
import android.widget.EditText

/** Ajustes de esta tableta. Se guardan solos al salir de la pantalla. */
class ClientConfigActivity : PantallaActivity() {

    private lateinit var prefs: Prefs
    private lateinit var campoEsp32: EditText
    private lateinit var campoPuertoEsp32: EditText
    private lateinit var campoPuertoVideo: EditText

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)

        val p = Ui.Pantalla(this)
        p.agregar(Ui.titulo(this, "Configurar cliente"))

        p.agregar(Ui.texto(this, "IP del ESP32-S3 (el que emula el control)"))
        campoEsp32 = p.agregar(Ui.campo(this, prefs.esp32Ip, soloIp = true))

        p.agregar(Ui.texto(this, "Puerto del ESP32 (por defecto 9000)"))
        campoPuertoEsp32 = p.agregar(Ui.campo(this, prefs.esp32Puerto.toString(), soloNumero = true))

        p.agregar(Ui.texto(this, "Puerto donde llega el video (por defecto 5000)"))
        campoPuertoVideo = p.agregar(Ui.campo(this, prefs.puertoVideo.toString(), soloNumero = true))

        p.agregar(
            Ui.opcion(
                this, "Ajuste de imagen",
                listOf(
                    "barras" to "barras negras (sin deformar)",
                    "estirar" to "estirar a toda la pantalla",
                    "zoom" to "llenar recortando bordes",
                ),
                prefs.ajusteImagen,
            ) { prefs.ajusteImagen = it },
        )

        p.agregar(
            Ui.opcion(
                this, "Frecuencia del mando",
                listOf(60, 90, 120, 180, 250).map { it.toString() to "$it Hz" },
                prefs.frecuenciaMando.toString(),
            ) { prefs.frecuenciaMando = it.toInt() },
        )

        p.agregar(
            Ui.opcion(
                this, "Botón PS (acorde)",
                listOf(
                    "SELECT+R1" to "SELECT + R1",
                    "SELECT+L1" to "SELECT + L1",
                    "SELECT+START" to "SELECT + START",
                    "none" to "ninguno (solo el botón Home/Guía del mando)",
                ),
                prefs.acordePs,
            ) { prefs.acordePs = it },
        )

        p.agregar(
            Ui.opcion(
                this, "Zona muerta de los sticks",
                listOf("nada" to "ninguna", "medio" to "media (6 %)", "alta" to "alta (12 %)"),
                prefs.zonaMuerta,
            ) { prefs.zonaMuerta = it },
        )

        p.agregar(
            Ui.opcion(
                this, "Cerrar si no hay video en",
                listOf(15, 25, 40, 60, 120).map { it.toString() to "$it s" },
                prefs.segundosSinVideo.toString(),
            ) { prefs.segundosSinVideo = it.toInt() },
        )

        p.agregar(Ui.texto(this, "Salir del streaming: L1 + R1 + SELECT + START a la vez."))
        p.agregar(Ui.boton(this, "Guardar y volver", 0xFF3F8F4A.toInt()) { finish() })

        setContentView(p.raiz)
    }

    override fun onPause() {
        super.onPause()
        val ip = campoEsp32.text.toString().trim()
        if (ip.isNotEmpty()) prefs.esp32Ip = ip
        campoPuertoEsp32.text.toString().toIntOrNull()?.takeIf { it in 1..65535 }?.let { prefs.esp32Puerto = it }
        campoPuertoVideo.text.toString().toIntOrNull()?.takeIf { it in 1..65535 }?.let { prefs.puertoVideo = it }
    }
}
