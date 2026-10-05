# ============================================================
#  start_server_gui.ps1 - interfaz grafica del servidor
# ============================================================
#  Estilo de mosaicos (2026-09-20), el mismo que el cliente Android, la
#  Deck y la Ally. La version anterior (un dialogo gris de WinForms) queda
#  como start_server_gui_clasica.ps1: si esta ventana falla al armarse por
#  lo que sea, se abre esa sola, para que nunca te quedes sin poder
#  encender el servidor (ver el catch de abajo).
#
#  Pide dos cosas y nada mas: a que IP mandar el video y en que modo.
#  Despues lanza start_server_stream.bat de siempre, con la ventana
#  OCULTA, pasandole la eleccion por variables de entorno (PS3RP_IP,
#  PS3RP_MODO, PS3RP_GUI) que el .bat ya sabe leer.
#
#  POR QUE NO REIMPLEMENTA FFMPEG: toda la sintonia de latencia del
#  proyecto vive comentada y justificada dentro del .bat. Duplicarla aqui
#  garantizaria que un dia las dos copias se separen. Esta interfaz es
#  solo la puerta de entrada; el motor sigue siendo el .bat, y la logica
#  de arranque/parada/config vive en server_engine_lib.ps1 (compartida
#  con config_listener.ps1). Esta ventana no define nada de eso.
#
#  QUE SE PIERDE AL OCULTAR LA VENTANA DEL MOTOR: la linea de estado de
#  ffmpeg en vivo (fps, speed). El diagnostico no se pierde: se guarda en
#  logs\progreso-<fecha>.log y logs\ffmpeg-<fecha>.log (revisar_log.bat).
#
#  No necesita instalar nada: WinForms viene con Windows, y el control de
#  los mosaicos es un poco de C# que Windows compila al abrir (Add-Type).
#  Solo texto ASCII a proposito: PowerShell 5.1 lee mal los acentos de un
#  .ps1 sin BOM.
#
#  Pruebas (no las usa nadie mas):
#    PS3RP_GUI_PRUEBA=<archivo.png>  arma la ventana, la dibuja a un PNG y
#                                    sale (no arranca nada ni toca el motor)
#    PS3RP_GUI_PRUEBA_SALIDA=1       arma la ventana y la cierra sola a los
#                                    1.5 s: comprueba que el proceso MUERE
# ============================================================

$Aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$Clasica = Join-Path $Aqui "start_server_gui_clasica.ps1"
$Carpeta = Join-Path $Aqui "logs"
New-Item -ItemType Directory -Force -Path $Carpeta | Out-Null
$LogErrorNueva = Join-Path $Carpeta "gui_nueva_error.log"
$ArchivoGuiPid = Join-Path $Carpeta "gui.pid"

$EnPrueba = [bool]$env:PS3RP_GUI_PRUEBA
$EnPruebaSalida = [bool]$env:PS3RP_GUI_PRUEBA_SALIDA
$EsPrueba = $EnPrueba -or $EnPruebaSalida

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

. (Join-Path $Aqui "server_engine_lib.ps1")

if (-not (Test-Path $Bat)) {
    [System.Windows.Forms.MessageBox]::Show(
        "No encontre start_server_stream.bat en:`n$Aqui`n`nLos dos archivos tienen que estar en la misma carpeta.",
        "Remote Play", "OK", "Error") | Out-Null
    exit 1
}

# ------------------------------------------------------------
#  Una sola ventana a la vez (2026-09-20). Cada vez que se abre el launcher
#  nace otro proceso de esta ventana con su propio icono en la bandeja; si
#  quedan varios, "Salir" solo mata al que tenia el icono en la mano. Al
#  arrancar se cierra la instancia anterior (mismo patron que el
#  config_listener: PID en un archivo y solo se mata si de verdad es un
#  powershell, porque un PID viejo puede haberse reciclado).
# ------------------------------------------------------------
if (-not $EsPrueba) {
    if (Test-Path $ArchivoGuiPid) {
        $previo = [string](Get-Content $ArchivoGuiPid -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($previo.Trim() -match '^\d+$' -and [int]$previo.Trim() -ne $PID) {
            $procPrevio = Get-Process -Id ([int]$previo.Trim()) -ErrorAction SilentlyContinue
            if ($procPrevio -and $procPrevio.ProcessName -eq "powershell") {
                Stop-Process -Id $procPrevio.Id -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Set-Content -Path $ArchivoGuiPid -Value $PID -Encoding Ascii
}

# ------------------------------------------------------------
#  Control de mosaico (C#): tarjeta redondeada con degradado, icono, titulo y
#  descripcion; al pasar el mouse (o con Tab) crece un poco y el borde blanco
#  aparece con una transicion suave (~150 ms), como en Android.
# ------------------------------------------------------------
$Codigo = @'
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace PS3RP
{
    public static class Ui
    {
        public static float Esc = 1f;
        public static Color Fondo = Color.FromArgb(18, 22, 28);
        public static Color Panel = Color.FromArgb(30, 37, 46);
        public static Color Texto = Color.FromArgb(233, 238, 243);
        public static Color Tenue = Color.FromArgb(147, 161, 176);

        [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
        public static void ActivarDpi() { try { SetProcessDPIAware(); } catch (Exception) { } }

        public static Color Mezclar(Color a, Color b, float f)
        {
            return Color.FromArgb((int)(a.R + (b.R - a.R) * f), (int)(a.G + (b.G - a.G) * f), (int)(a.B + (b.B - a.B) * f));
        }

        public static GraphicsPath Redondeado(Rectangle r, int radio)
        {
            int d = radio * 2;
            GraphicsPath p = new GraphicsPath();
            p.AddArc(r.X, r.Y, d, d, 180, 90);
            p.AddArc(r.Right - d, r.Y, d, d, 270, 90);
            p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
            p.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
            p.CloseFigure();
            return p;
        }
    }

    public class Mosaico : Control
    {
        public Color ColorBase = Color.FromArgb(45, 108, 223);
        public string Titulo = "";
        public string Detalle = "";
        public Image Icono;
        public bool Marcado;
        public bool Horizontal;
        public float TamTitulo = 13f;
        public float TamDetalle = 9f;
        public int LadoIcono = 36;
        public int Pad = 0;   // margen interno en px a 96 dpi (0 = automatico)
        public Color ColorTexto = Color.White;

        float t = 0f, objetivo = 0f;
        Timer timer = new Timer();

        public Mosaico()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            TabStop = true;
            Cursor = Cursors.Hand;
            BackColor = Ui.Fondo;
            timer.Interval = 15;
            timer.Tick += delegate { Paso(); };
        }

        public void PerformClick() { OnClick(EventArgs.Empty); }
        public void Resaltar(float v) { t = v; objetivo = v; Invalidate(); }   // para pruebas

        void Mover(float destino) { objetivo = destino; if (!timer.Enabled) timer.Start(); }

        void Paso()
        {
            float d = objetivo - t;
            if (Math.Abs(d) < 0.02f) { t = objetivo; timer.Stop(); }
            else t += d * 0.35f;
            Invalidate();
        }

        protected override void OnMouseEnter(EventArgs e) { base.OnMouseEnter(e); if (Enabled) Mover(1f); }
        protected override void OnMouseLeave(EventArgs e) { base.OnMouseLeave(e); if (!(Focused && ShowFocusCues)) Mover(0f); }
        protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); if (ShowFocusCues) Mover(1f); }
        protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Mover(0f); }
        protected override void OnEnabledChanged(EventArgs e) { base.OnEnabledChanged(e); if (!Enabled) Mover(0f); Cursor = Enabled ? Cursors.Hand : Cursors.Default; Invalidate(); }
        protected override bool IsInputKey(Keys k) { return k == Keys.Enter || k == Keys.Space || base.IsInputKey(k); }
        protected override void OnKeyDown(KeyEventArgs e)
        {
            base.OnKeyDown(e);
            if (Enabled && (e.KeyCode == Keys.Enter || e.KeyCode == Keys.Space)) { OnClick(EventArgs.Empty); e.Handled = true; }
        }
        protected override void Dispose(bool disposing) { if (disposing) timer.Dispose(); base.Dispose(disposing); }

        protected override void OnPaint(PaintEventArgs pe)
        {
            Graphics g = pe.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.InterpolationMode = InterpolationMode.HighQualityBicubic;
            g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
            g.Clear(Ui.Fondo);
            if (Width < 20 || Height < 20) return;

            float esc = Ui.Esc;
            int m = (int)Math.Round(7 * esc * (1 - t) + 1 * esc * t);   // el margen se achica: la tarjeta crece
            Rectangle r = new Rectangle(m, m, Width - 2 * m, Height - 2 * m);
            Color c = Enabled ? ColorBase : Ui.Mezclar(ColorBase, Ui.Fondo, 0.55f);
            int radio = (int)(18 * esc);

            using (GraphicsPath path = Ui.Redondeado(r, radio))
            using (LinearGradientBrush br = new LinearGradientBrush(r, Ui.Mezclar(c, Color.White, 0.16f), c, 90f))
            {
                g.FillPath(br, path);
                if (t > 0.02f)
                {
                    using (Pen p = new Pen(Color.FromArgb((int)(255 * Math.Min(1f, t)), Color.White), 4 * esc))
                    {
                        p.LineJoin = LineJoin.Round;
                        g.DrawPath(p, path);
                    }
                }
            }

            int pad = (int)((Pad > 0 ? Pad : (Horizontal ? 16 : 22)) * esc);
            Color ct = Enabled ? ColorTexto : Ui.Mezclar(ColorTexto, c, 0.4f);
            Color cd = Ui.Mezclar(ct, c, 0.12f);
            int lado = Icono != null ? (int)(LadoIcono * esc) : 0;

            using (Font ft = new Font("Segoe UI", TamTitulo, FontStyle.Bold))
            using (Font fd = new Font("Segoe UI", TamDetalle))
            using (Brush bt = new SolidBrush(ct))
            using (Brush bd = new SolidBrush(cd))
            using (StringFormat sf = new StringFormat(StringFormatFlags.NoClip))
            {
                sf.Trimming = StringTrimming.EllipsisWord;
                if (Horizontal)
                {
                    int x = pad;
                    if (lado > 0) { g.DrawImage(Icono, new Rectangle(x, (Height - lado) / 2, lado, lado)); x += lado + (int)(12 * esc); }
                    int ancho = Math.Max(20, Width - x - pad - (Marcado ? (int)(24 * esc) : 0));   // deja lugar a la palomita
                    SizeF st = g.MeasureString(Titulo, ft, ancho, sf);
                    SizeF sd = string.IsNullOrEmpty(Detalle) ? SizeF.Empty : g.MeasureString(Detalle, fd, ancho, sf);
                    float total = st.Height + (sd.Height > 0 ? 2 * esc + sd.Height : 0);
                    float y = (Height - total) / 2;
                    g.DrawString(Titulo, ft, bt, new RectangleF(x, y, ancho, st.Height), sf);
                    if (sd.Height > 0) g.DrawString(Detalle, fd, bd, new RectangleF(x, y + st.Height + 2 * esc, ancho, sd.Height), sf);
                }
                else
                {
                    int ancho = Math.Max(20, Width - 2 * pad);
                    SizeF st = g.MeasureString(Titulo, ft, ancho, sf);
                    SizeF sd = string.IsNullOrEmpty(Detalle) ? SizeF.Empty : g.MeasureString(Detalle, fd, ancho, sf);
                    float total = (lado > 0 ? lado + 8 * esc : 0) + st.Height + (sd.Height > 0 ? 3 * esc + sd.Height : 0);
                    float y = Math.Max(6 * esc, (Height - total) / 2);
                    if (lado > 0) { g.DrawImage(Icono, new Rectangle(pad, (int)y, lado, lado)); y += lado + 8 * esc; }
                    g.DrawString(Titulo, ft, bt, new RectangleF(pad, y, ancho, st.Height), sf);
                    y += st.Height + 3 * esc;
                    if (sd.Height > 0) g.DrawString(Detalle, fd, bd, new RectangleF(pad, y, ancho, sd.Height), sf);
                }
            }

            if (Marcado)
            {
                int rad = (int)(10 * esc);
                int cx = r.Right - (int)(20 * esc);
                int cy = r.Y + (int)(20 * esc);
                g.FillEllipse(Brushes.White, cx - rad, cy - rad, rad * 2, rad * 2);
                using (Pen p = new Pen(c, Math.Max(2f, 2.5f * esc)))
                {
                    p.StartCap = LineCap.Round; p.EndCap = LineCap.Round; p.LineJoin = LineJoin.Round;
                    g.DrawLines(p, new PointF[] { new PointF(cx - rad * 0.45f, cy), new PointF(cx - rad * 0.1f, cy + rad * 0.35f), new PointF(cx + rad * 0.5f, cy - rad * 0.35f) });
                }
            }
        }
    }

    // Tira redondeada con un punto de color y un mensaje (el estado del servidor).
    public class Tira : Control
    {
        public Color Punto = Ui.Tenue;
        public string Mensaje = "";

        public Tira()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            BackColor = Ui.Fondo;
        }

        public void Poner(Color punto, string mensaje) { Punto = punto; Mensaje = mensaje; Invalidate(); }

        protected override void OnPaint(PaintEventArgs pe)
        {
            Graphics g = pe.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
            g.Clear(Ui.Fondo);
            if (Width < 20 || Height < 20) return;
            float esc = Ui.Esc;
            Rectangle r = new Rectangle(0, 0, Width - 1, Height - 1);
            using (GraphicsPath path = Ui.Redondeado(r, (int)(14 * esc)))
            using (Brush fondo = new SolidBrush(Ui.Panel))
                g.FillPath(fondo, path);
            int rad = (int)(7 * esc);
            using (Brush b = new SolidBrush(Punto))
                g.FillEllipse(b, (int)(20 * esc) - rad, Height / 2 - rad, rad * 2, rad * 2);
            using (Font f = new Font("Segoe UI", 10.5f))
            using (Brush bt = new SolidBrush(Ui.Texto))
            using (StringFormat sf = new StringFormat())
            {
                sf.LineAlignment = StringAlignment.Center;
                sf.Trimming = StringTrimming.EllipsisWord;
                int x = (int)(42 * esc);
                g.DrawString(Mensaje, f, bt, new RectangleF(x, 0, Width - x - 14 * esc, Height), sf);
            }
        }
    }
}
'@

# ------------------------------------------------------------
#  Construccion de la ventana. Si algo falla ANTES de mostrarla (el C#
#  no compila, falta un icono raro, etc.), se abre la ventana clasica.
# ------------------------------------------------------------
try {
    Add-Type -TypeDefinition $Codigo -ReferencedAssemblies "System.Windows.Forms", "System.Drawing"
    [PS3RP.Ui]::ActivarDpi()
    $dc = [System.Drawing.Graphics]::FromHwnd([IntPtr]::Zero)
    [PS3RP.Ui]::Esc = [float]($dc.DpiX / 96.0)
    $dc.Dispose()

    function E([double]$n) { return [int][math]::Round($n * [PS3RP.Ui]::Esc) }
    function C([int]$r, [int]$g, [int]$b) { return [System.Drawing.Color]::FromArgb($r, $g, $b) }

    $colFondo  = C 18 22 28
    $colPanel  = C 30 37 46
    $colTexto  = C 233 238 243
    $colTenue  = C 147 161 176
    $colAzul   = C 45 108 223
    $colVerde  = C 63 143 74
    $colMorado = C 142 95 214
    $colGris   = C 42 52 65
    $colRojo   = C 176 58 58
    $colOk     = C 61 220 132
    $colAviso  = C 255 183 77
    $colError  = C 255 107 107

    # Dispositivos conocidos: un clic elige su IP. Si cambian de IP, se editan aqui.
    $Dispositivos = @(
        @{ Nombre = "Steam Deck";  Ip = "192.168.0.141"; Icono = "gamepad" },
        @{ Nombre = "ROG Ally X";  Ip = "192.168.0.53";  Icono = "gamepad" },
        @{ Nombre = "Tableta";     Ip = "192.168.0.153"; Icono = "tablet" }
    )

    function Cargar-Icono([string]$nombre, [int]$lado) {
        $disco = 40
        if ($lado -ge 56) { $disco = 72 }
        $ruta = Join-Path $Aqui ("iconos\{0}_{1}.png" -f $nombre, $disco)
        if (Test-Path $ruta) { try { return (New-Object System.Drawing.Bitmap($ruta)) } catch { } }
        return $null
    }

    function Obtener-IpLocal {
        try {
            $s = New-Object System.Net.Sockets.UdpClient
            $s.Connect("8.8.8.8", 53)
            $ip = $s.Client.LocalEndPoint.Address.ToString()
            $s.Close()
            return $ip
        } catch { return "" }
    }

    # ---- ventana ----
    $form                 = New-Object System.Windows.Forms.Form
    $form.Text            = "Remote Play - Servidor"
    $form.AutoScaleMode   = "None"
    $form.ClientSize      = New-Object System.Drawing.Size((E 800), (E 660))
    $form.StartPosition   = "CenterScreen"
    $form.FormBorderStyle = "FixedSingle"
    $form.MaximizeBox     = $false
    $form.BackColor       = $colFondo
    $form.ForeColor       = $colTexto
    $form.Font            = New-Object System.Drawing.Font("Segoe UI", 9)

    # Icono real del proyecto, el mismo de branding/deck-client.
    $IconoArchivo = Join-Path $Aqui "server_icon.ico"
    if (Test-Path $IconoArchivo) {
        try { $form.Icon = New-Object System.Drawing.Icon($IconoArchivo) } catch {}
    }

    function Nuevo-Label([string]$texto, $x, $y, $w, $h, [double]$tam, [bool]$negrita, $color, $alineacion = "MiddleLeft") {
        $l = New-Object System.Windows.Forms.Label
        $l.Text = $texto
        $l.SetBounds((E $x), (E $y), (E $w), (E $h))
        $estilo = [System.Drawing.FontStyle]::Regular
        if ($negrita) { $estilo = [System.Drawing.FontStyle]::Bold }
        $l.Font = New-Object System.Drawing.Font("Segoe UI", $tam, $estilo)
        $l.ForeColor = $color
        $l.BackColor = $colFondo
        $l.TextAlign = $alineacion
        $form.Controls.Add($l)
        return $l
    }

    function Nuevo-Mosaico([string]$titulo, [string]$detalle, $color, [string]$icono, $x, $y, $w, $h, [double]$tamT = 12, [double]$tamD = 9, [bool]$horizontal = $false, [int]$lado = 36, [int]$pad = 0) {
        $t = New-Object PS3RP.Mosaico
        $t.Pad = $pad
        $t.Titulo = $titulo
        $t.Detalle = $detalle
        $t.ColorBase = $color
        $t.TamTitulo = $tamT
        $t.TamDetalle = $tamD
        $t.Horizontal = $horizontal
        $t.LadoIcono = $lado
        $t.Icono = (Cargar-Icono $icono $lado)
        $t.SetBounds((E $x), (E $y), (E $w), (E $h))
        $form.Controls.Add($t)
        return $t
    }

    $m = 24                    # margen lateral
    $anchoTotal = 800 - 2 * $m

    # ---- cabecera ----
    [void](Nuevo-Label "Remote Play - Servidor" $m 14 480 40 20 $true $colTexto)
    $ipLocal = Obtener-IpLocal
    if ($ipLocal) { [void](Nuevo-Label ("Esta PC: " + $ipLocal) (800 - $m - 260) 22 260 28 10 $false $colTenue "MiddleRight") }

    # ---- tira de estado ----
    $tira = New-Object PS3RP.Tira
    $tira.SetBounds((E $m), (E 60), (E $anchoTotal), (E 54))
    $form.Controls.Add($tira)

    # ---- destino del video ----
    [void](Nuevo-Label "Enviar el video a" $m 126 400 24 11 $true $colTexto)

    # IP: DropDown (no DropDownList) a proposito: lista las guardadas pero deja escribir una nueva.
    $cmbIp               = New-Object System.Windows.Forms.ComboBox
    $cmbIp.SetBounds((E ($m + 112)), (E 263), (E 260), (E 28))
    $cmbIp.DropDownStyle = "DropDown"
    $cmbIp.FlatStyle     = "Flat"
    $cmbIp.BackColor     = $colPanel
    $cmbIp.ForeColor     = $colTexto
    $cmbIp.Font          = New-Object System.Drawing.Font("Segoe UI", 11)
    foreach ($ip in (Leer-Ips)) { [void]$cmbIp.Items.Add($ip) }
    $cmbIp.SelectedIndex = 0
    $form.Controls.Add($cmbIp)

    $tilesDisp = @()
    $gap = 12
    $ancho4 = [math]::Floor(($anchoTotal - 3 * $gap) / 4)
    for ($k = 0; $k -lt $Dispositivos.Count; $k++) {
        $d = $Dispositivos[$k]
        $t = Nuevo-Mosaico $d.Nombre $d.Ip $colAzul $d.Icono ($m + $k * ($ancho4 + $gap)) 154 $ancho4 100 12 9 $true 32
        # El dato va en Tag (y no en un closure): un closure no siempre ve las funciones del script.
        $t.Tag = $d.Ip
        $t.Add_Click({ param($s, $e) $cmbIp.Text = [string]$s.Tag })
        $tilesDisp += $t
    }
    $tileOtra = Nuevo-Mosaico "Otra IP" "escribela abajo" $colGris "wifi" ($m + 3 * ($ancho4 + $gap)) 154 $ancho4 100 12 9 $true 32
    $tileOtra.Add_Click({ $cmbIp.Focus(); $cmbIp.SelectAll() })

    [void](Nuevo-Label "IP de destino:" $m 262 108 30 10 $false $colTenue)

    function Sincronizar-Dispositivos {
        $ipTxt = $cmbIp.Text.Trim()
        $hay = $false
        for ($k = 0; $k -lt $tilesDisp.Count; $k++) {
            $coincide = ($Dispositivos[$k].Ip -eq $ipTxt)
            if ($coincide) { $hay = $true }
            $tilesDisp[$k].Marcado = $coincide
            $tilesDisp[$k].Invalidate()
        }
        $tileOtra.Marcado = (-not $hay)
        $tileOtra.Invalidate()
    }
    $cmbIp.Add_TextChanged({ Sincronizar-Dispositivos })

    # ---- modo de captura ----
    [void](Nuevo-Label "Resolucion / modo de captura" $m 304 400 24 11 $true $colTexto)
    $tilesModo = @()
    $ancho5 = [math]::Floor(($anchoTotal - 4 * 10) / 5)
    for ($k = 0; $k -lt $Modos.Count; $k++) {
        $nombre = ($Modos[$k].Nombre -replace '\s{2,}', ' ')
        $titulo = $nombre
        $detalle = ""
        if ($nombre -match '^\s*(\d+x\d+)\s*-\s*(.*)$') { $titulo = $Matches[1]; $detalle = $Matches[2] }
        $t = Nuevo-Mosaico $titulo $detalle $colMorado "image" ($m + $k * ($ancho5 + 10)) 332 $ancho5 124 13 8.5 $false 28 14
        $t.Tag = $k
        $t.Add_Click({ param($s, $e) Elegir-Modo ([int]$s.Tag) })
        $tilesModo += $t
    }

    # Explica el modo elegido: aqui vive el "por que" de cada opcion, para no elegir a ciegas.
    $lblAyuda = Nuevo-Label "" $m 462 $anchoTotal 44 9.5 $false $colTenue "TopLeft"

    $script:ModoIdx = 0
    function Elegir-Modo([int]$i) {
        $script:ModoIdx = $i
        for ($k = 0; $k -lt $tilesModo.Count; $k++) {
            $tilesModo[$k].Marcado = ($k -eq $i)
            $tilesModo[$k].Invalidate()
        }
        $lblAyuda.Text = $Modos[$i].Ayuda
    }

    # Preseleccion: el ultimo modo usado, o el recomendado.
    $indice = 0
    if (Test-Path $ArchivoModo) {
        $guardado = (Get-Content $ArchivoModo -First 1 -ErrorAction SilentlyContinue)
        if ($guardado) {
            $guardado = $guardado.Trim()
            for ($i = 0; $i -lt $Modos.Count; $i++) {
                if ($Modos[$i].Clave -eq $guardado) { $indice = $i }
            }
        }
    }
    Elegir-Modo $indice
    Sincronizar-Dispositivos

    # ---- acciones ----
    $yAcc = 518
    $btnIniciar = Nuevo-Mosaico "Iniciar servidor" "" $colVerde "play" $m $yAcc 220 72 12.5 9 $true 30
    $btnDetener = Nuevo-Mosaico "Detener servidor" "" $colRojo "power" ($m + 220 + $gap) $yAcc 200 72 12.5 9 $true 30
    $btnLogs    = Nuevo-Mosaico "Ver logs" "" $colGris "info" ($m + 220 + 200 + 2 * $gap) $yAcc 150 72 12 9 $true 28
    $btnCerrar  = Nuevo-Mosaico "Cerrar" "" $colGris "back" ($m + 220 + 200 + 150 + 3 * $gap) $yAcc ($anchoTotal - 220 - 200 - 150 - 3 * $gap) 72 12 9 $true 28
    $btnCerrar.Add_Click({ $form.Close() })

    [void](Nuevo-Label "Cerrar esta ventana no detiene el servidor: queda en la bandeja. Salir, en el icono de la bandeja, apaga todo (servidor y escucha). Tambien se puede configurar desde la Deck, la Ally y la tableta." $m 604 $anchoTotal 44 9 $false $colTenue "TopLeft")

    $btnLogs.Add_Click({
        $carpeta = Join-Path $Aqui "logs"
        if (Test-Path $carpeta) { Start-Process explorer.exe $carpeta }
        else {
            [System.Windows.Forms.MessageBox]::Show(
                "Todavia no hay logs: se crean en la primera corrida.",
                "Remote Play", "OK", "Information") | Out-Null
        }
    })

    # ---- estado ----
    function Nombre-Destino([string]$ip) {
        foreach ($d in $Dispositivos) { if ($d.Ip -eq $ip) { return ("{0} ({1})" -f $d.Nombre, $ip) } }
        return $ip
    }

    $script:Arrancando = $false

    function Refrescar-Estado {
        if (Servidor-Corriendo) {
            $ipDest = ""
            if (Test-Path $ArchivoIp) { $ipDest = [string](Get-Content $ArchivoIp -First 1 -ErrorAction SilentlyContinue) }
            $nomModo = ""
            if (Test-Path $ArchivoModo) {
                $claveModo = ([string](Get-Content $ArchivoModo -First 1 -ErrorAction SilentlyContinue)).Trim()
                foreach ($mm in $Modos) { if ($mm.Clave -eq $claveModo) { $nomModo = ($mm.Nombre -replace '\s{2,}', ' ') } }
            }
            if (Servidor-Transmitiendo) {
                $tira.Poner($colOk, ("Transmitiendo a " + (Nombre-Destino $ipDest.Trim()) + "  -  " + $nomModo))
            } else {
                $tira.Poner($colAviso, "Corriendo, pero todavia sin video (revisa la capturadora si sigue asi).")
            }
            $btnIniciar.Titulo = "Reiniciar servidor"
            $btnDetener.Enabled = $true
        } else {
            $tira.Poner($colTenue, "Detenido")
            $btnIniciar.Titulo = "Iniciar servidor"
            $btnDetener.Enabled = $false
        }
        $btnIniciar.Invalidate()
    }

    $btnDetener.Add_Click({
        # Cierra la ventana tambien (2026-09-11, pedido explicito): "Detener servidor" es un
        # stop-y-cierra (la ventana se oculta a la bandeja), igual que el boton Cerrar pero
        # deteniendo el motor primero.
        if (Detener-Servidor-APedido) {
            $form.Close()
        } else {
            Refrescar-Estado
            [System.Windows.Forms.MessageBox]::Show(
                "No habia ningun servidor corriendo.",
                "Remote Play", "OK", "Information") | Out-Null
            $form.Close()
        }
    })

    $btnIniciar.Add_Click({
        $ip = $cmbIp.Text.Trim()

        # Misma validacion floja que el .bat: 4 grupos de digitos. Vale la pena atraparla aqui
        # porque una IP mal escrita no da NINGUN error visible: ffmpeg manda UDP feliz al vacio
        # y en el cliente se ve pantalla negra.
        if ($ip -notmatch $RegexIp) {
            [System.Windows.Forms.MessageBox]::Show(
                "`"$ip`" no parece una IP.`n`nTiene que ser algo como 192.168.0.141",
                "IP invalida", "OK", "Warning") | Out-Null
            return
        }

        $modo = $Modos[$script:ModoIdx].Clave

        $script:Arrancando = $true
        $btnIniciar.Enabled = $false
        $btnDetener.Enabled = $false

        $avisar = {
            param($msg)
            $tira.Poner($colAviso, $msg)
            [System.Windows.Forms.Application]::DoEvents()
        }

        try {
            $arranco = Iniciar-Servidor $ip $modo $avisar
        } finally {
            $script:Arrancando = $false
        }

        $btnIniciar.Enabled = $true
        Refrescar-Estado

        if (-not $arranco) {
            # Dejar rastro de POR QUE se concluyo que no arranco, para poder diagnosticarlo
            # despues sin tener que reproducirlo en vivo.
            try {
                $dbg = @()
                $dbg += "fecha: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
                $dbg += "sesion de esta ventana: $((Get-Process -Id $PID).SessionId)"
                $procs = @(Get-Process -Name 'ffmpeg' -ErrorAction SilentlyContinue)
                $dbg += "Get-Process ffmpeg encontro: $($procs.Count)"
                foreach ($q in $procs) {
                    $ruta = 'NO SE PUDO LEER'
                    try { if ($q.Path) { $ruta = $q.Path } } catch { $ruta = "ERROR: $($_.Exception.Message)" }
                    $dbg += "  pid=$($q.Id) sesion=$($q.SessionId) ruta=$ruta"
                }
                $dbg += "FfmpegExe esperado: $FfmpegExe"
                $dbg += "Procesos-Servidor devolvio: $((Procesos-Servidor | Measure-Object).Count)"
                $ultimo = Get-ChildItem "$Aqui\logs\progreso-*.log" -ErrorAction SilentlyContinue |
                          Sort-Object LastWriteTime -Descending | Select-Object -First 1
                if ($ultimo) { $dbg += "ultimo progreso log: $($ultimo.Name) $($ultimo.Length) bytes, $($ultimo.LastWriteTime)" }
                $dbg -join "`r`n" | Set-Content "$Aqui\diagnostico_no_arranco.txt" -Encoding UTF8
            } catch { }

            $tira.Poner($colError, "No arranco")
            [System.Windows.Forms.MessageBox]::Show(
                "El servidor no llego a arrancar en 15 segundos.`n`nLo mas comun es que la capturadora este desconectada o que Windows le haya cambiado el nombre al cambiarla de puerto USB.`n`nRevisa los logs con el boton de abajo, o abre start_server_stream.bat a mano (con la ventana visible) para ver el error.",
                "Remote Play", "OK", "Warning") | Out-Null
        }
    })

    # ---- refresco de config aplicada en remoto (2026-09-11) ----
    # config_listener.ps1 corre en OTRO proceso: si la Deck/Ally/tableta cambia el modo o la IP
    # mientras esta ventana esta abierta, los archivos cambian en disco pero esta ventana solo los
    # leyo UNA vez. Un timer cada 2 s los vuelve a leer y sincroniza, sin pisar el cuadro de IP
    # mientras se esta editando (-not Focused) ni los mensajes de un arranque en curso.
    $script:UltimoModoVisto = $Modos[$script:ModoIdx].Clave
    $script:UltimaIpVista   = $cmbIp.Text

    $timerRefrescoRemoto = New-Object System.Windows.Forms.Timer
    $timerRefrescoRemoto.Interval = 2000
    $timerRefrescoRemoto.Add_Tick({
        if ($script:Arrancando) { return }
        $modoActual = $null
        if (Test-Path $ArchivoModo) { $modoActual = (Get-Content $ArchivoModo -First 1 -ErrorAction SilentlyContinue) }
        if ($modoActual) {
            $modoActual = $modoActual.Trim()
            if ($modoActual -ne $script:UltimoModoVisto) {
                $script:UltimoModoVisto = $modoActual
                for ($i = 0; $i -lt $Modos.Count; $i++) {
                    if ($Modos[$i].Clave -eq $modoActual) { Elegir-Modo $i; break }
                }
            }
        }

        $ipActual = $null
        if (Test-Path $ArchivoIp) { $ipActual = (Get-Content $ArchivoIp -First 1 -ErrorAction SilentlyContinue) }
        if ($ipActual) {
            $ipActual = $ipActual.Trim()
            if ($ipActual -ne $script:UltimaIpVista) {
                $script:UltimaIpVista = $ipActual
                if (-not $cmbIp.Focused) { $cmbIp.Text = $ipActual }
            }
        }

        Refrescar-Estado
    })

    Refrescar-Estado

    # ---- solo para pruebas: dibujar a un PNG y salir (no arranca nada ni toca el motor) ----
    if ($EnPrueba) {
        $form.Show()
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 300
        # un mosaico con el "hover" a medias y otro completo, para ver la animacion
        $tilesDisp[1].Resaltar(1.0)
        $tilesModo[2].Resaltar(0.5)
        [System.Windows.Forms.Application]::DoEvents()
        $bmp = New-Object System.Drawing.Bitmap($form.Width, $form.Height)
        $form.DrawToBitmap($bmp, (New-Object System.Drawing.Rectangle(0, 0, $form.Width, $form.Height)))
        $bmp.Save($env:PS3RP_GUI_PRUEBA, [System.Drawing.Imaging.ImageFormat]::Png)
        Write-Output ("PNG guardado: " + $env:PS3RP_GUI_PRUEBA + " ({0}x{1})" -f $form.Width, $form.Height)
        exit 0
    }
}
catch {
    try {
        ("[{0}] La ventana nueva fallo al armarse: {1}`r`n{2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $_.Exception.Message, $_.ScriptStackTrace) |
            Add-Content -Path $LogErrorNueva -Encoding UTF8
    } catch { }
    if (Test-Path $Clasica) {
        # Plan B: la ventana de siempre. Nunca dejar al usuario sin poder encender el servidor.
        & $Clasica
        exit
    }
    [System.Windows.Forms.MessageBox]::Show(
        "La ventana nueva fallo y no encontre start_server_gui_clasica.ps1.`n`n$($_.Exception.Message)",
        "Remote Play", "OK", "Error") | Out-Null
    exit 1
}

# ------------------------------------------------------------
#  Bandeja del sistema, salida y arranque
# ------------------------------------------------------------

# Termina ESTE proceso de verdad (2026-09-20, pedido explicito: "que al salir desde el iconito de
# la bandeja mate la instancia en realidad"). Quita el icono (si no, queda un fantasma en la
# bandeja), borra el PID y fuerza la salida: nada de esperar a que el bucle de mensajes muera solo.
function Terminar-Proceso {
    try { $trayIcon.Visible = $false; $trayIcon.Dispose() } catch { }
    Remove-Item $ArchivoGuiPid -Force -ErrorAction SilentlyContinue
    [Environment]::Exit(0)
}

# Icono en la bandeja (2026-09-12): al auto-iniciar, la ventana se OCULTA (no minimiza) y queda este
# icono; un click la vuelve a mostrar.
$trayIcon = New-Object System.Windows.Forms.NotifyIcon
$trayIcon.Text = "Remote Play - Servidor"
$trayIcon.Icon = if ($form.Icon) { $form.Icon } else { [System.Drawing.SystemIcons]::Application }
$trayIcon.Visible = $true

$mostrarVentana = {
    $form.Show()
    $form.WindowState = "Normal"
    $form.Activate()
}
# MouseClick con boton izquierdo (no Click a secas): Click de NotifyIcon dispara con CUALQUIER
# boton, asi que el clic derecho para abrir el menu tambien abriria la ventana de encima. Solo
# abre la UI - nunca toca Iniciar-Servidor ni reinicia nada.
$trayIcon.Add_MouseClick({
    param($s, $e)
    if ($e.Button -eq [System.Windows.Forms.MouseButtons]::Left) { & $mostrarVentana }
})
$trayIcon.Add_DoubleClick($mostrarVentana)

$script:SalirDeVerdad = $false

# "Salir" apaga TODO (2026-09-18, pedido explicito): el motor (ffmpeg y su cmd), la marca de
# "servidor deseado" (para que el auto-reinicio no lo vuelva a prender), el config_listener (que si
# no seguiria contestando a la Deck/Ally con "corriendo") y, al final, esta misma ventana.
$apagarTodo = {
    try { [void](Detener-Servidor-APedido) } catch { }
    try {
        $archivoListener = Join-Path $Aqui "logs\config_listener.pid"
        if (Test-Path $archivoListener) {
            $pidListener = [string](Get-Content $archivoListener -ErrorAction SilentlyContinue | Select-Object -First 1)
            if ($pidListener.Trim() -match '^\d+$' -and [int]$pidListener.Trim() -ne $PID) {
                $procListener = Get-Process -Id ([int]$pidListener.Trim()) -ErrorAction SilentlyContinue
                # Solo si de verdad es un powershell: un PID viejo puede haberse reciclado.
                if ($procListener -and $procListener.ProcessName -eq "powershell") {
                    Stop-Process -Id $procListener.Id -Force -ErrorAction SilentlyContinue
                }
            }
            Remove-Item $archivoListener -Force -ErrorAction SilentlyContinue
        }
    } catch { }
}

function Salir-De-Verdad {
    try { $trayIcon.Visible = $false } catch { }      # el icono desaparece YA
    & $apagarTodo
    $script:SalirDeVerdad = $true
    # Red de seguridad: si por lo que sea el cierre de la ventana no termina el proceso, a los 3 s
    # se fuerza la salida.
    $script:TimerSalida = New-Object System.Windows.Forms.Timer
    $script:TimerSalida.Interval = 3000
    $script:TimerSalida.Add_Tick({ Terminar-Proceso })
    $script:TimerSalida.Start()
    $form.Close()
}

$menuTray = New-Object System.Windows.Forms.ContextMenuStrip
[void]$menuTray.Items.Add("Abrir", $null, $mostrarVentana)
[void]$menuTray.Items.Add("Salir (apaga todo)", $null, { Salir-De-Verdad })
$trayIcon.ContextMenuStrip = $menuTray

# Cerrar (la X, el boton "Cerrar", o Detener) oculta a la bandeja en vez de salir - "Salir" del menu
# de la bandeja es la unica forma de cerrar de verdad. EXCEPCION (2026-09-20): si Windows se apaga o
# cierra la sesion, o alguien termina el proceso, NO se cancela el cierre (antes esta ventana
# bloqueaba el apagado de Windows). El motor sigue corriendo aparte de todos modos.
$form.Add_FormClosing({
    param($s, $e)
    $razones = @('WindowsShutDown', 'TaskManagerClosing', 'ApplicationExitCall')
    if (-not $script:SalirDeVerdad -and ($razones -notcontains [string]$e.CloseReason)) {
        $e.Cancel = $true
        $form.Hide()
    } else {
        try { $trayIcon.Visible = $false } catch { }
    }
})

if ($EnPruebaSalida) {
    # Solo prueba: cerrar sola a los 1.5 s, como si se hubiera elegido Salir (SIN apagar el motor ni
    # el escucha), para comprobar desde afuera que el proceso realmente MUERE.
    $script:TimerPrueba = New-Object System.Windows.Forms.Timer
    $script:TimerPrueba.Interval = 1500
    $script:TimerPrueba.Add_Tick({
        $script:TimerPrueba.Stop()
        $script:SalirDeVerdad = $true
        try { $trayIcon.Visible = $false } catch { }
        $form.Close()
    })
    $script:TimerPrueba.Start()
} else {
    $timerRefrescoRemoto.Start()
    # Auto-inicio y ocultado al abrir (2026-09-12, pedido explicito): usa la IP/modo ya cargados
    # (ultimos guardados), arranca solo y se oculta a la bandeja en vez de dejar la ventana abierta.
    $form.Add_Shown({
        $btnIniciar.PerformClick()
        $form.Hide()
    })
}

# Application.Run y NO ShowDialog() (2026-09-12, causa real de "se cierra todo al ocultarla"):
# ShowDialog() liga su bucle modal a la visibilidad de la ventana - en cuanto se llama $form.Hide(),
# Windows Forms lo trata como si el dialogo hubiera terminado y cierra el proceso entero.
# Application.Run mantiene vivo el programa mientras la ventana este oculta; solo termina cuando el
# form se CIERRA de verdad (el "Salir" de la bandeja).
[System.Windows.Forms.Application]::Run($form)
Terminar-Proceso
