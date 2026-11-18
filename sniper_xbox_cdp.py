#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Xbox Direct DOM Code Sniper
===========================
Herramienta de Computer Vision y Automatización Web de baja latencia (Playwright CDP).
Captura una región de un stream en tiempo real (30-60 FPS), extrae códigos vía OCR
y los inyecta directamente en el DOM/iframe de xbox.com/redeem sin usar ratón ni portapapeles.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from typing import Optional, Tuple

import cv2
import keyboard
import mss
import numpy as np
import pyautogui
import pytesseract
import winsound
from playwright.sync_api import Browser, Frame, Locator, Page, Playwright, sync_playwright

# ==============================================================================
# CONFIGURACIÓN GLOBAL Y CONSTANTES
# ==============================================================================
CDP_URL = "http://localhost:9222"
CONFIG_FILE = "config_cdp.json"
LOG_FILE = "codigos_cazados.txt"
CHROME_PROFILE_DIR = r"C:\chrome_sniper_profile"

# Rutas habituales de Tesseract en Windows por si no está en el PATH
TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
]

# Selectores candidatos para el input de 25 caracteres dentro de xbox.com/redeem (iframe redeem.microsoft.com)
INPUT_SELECTORS = [
    "input[name*='token' i]",
    "input[id*='token' i]",
    "input[placeholder*='XXXXX' i]",
    "input[aria-label*='25' i]",
    "input[aria-label*='code' i]",
    "input[aria-label*='código' i]",
    "input[type='text']",
    "input:not([type='hidden'])",
]

# Selectores candidatos para el botón de confirmación / canje
CONFIRM_BUTTON_SELECTORS = [
    "button[type='submit']:not([disabled])",
    "button:has-text('Confirmar'):not([disabled])",
    "button:has-text('Confirm'):not([disabled])",
    "button:has-text('Siguiente'):not([disabled])",
    "button:has-text('Next'):not([disabled])",
    "button:has-text('Canjear'):not([disabled])",
    "button:has-text('Redeem'):not([disabled])",
    "input[type='submit']:not([disabled])",
]

# Patrones Regex disponibles
REGEX_PATTERNS = {
    "1": {
        "nombre": "Xbox Estándar (25 caracteres: XXXXX-XXXXX-XXXXX-XXXXX-XXXXX)",
        "regex": re.compile(
            r"\b[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}\b"
        ),
    },
    "2": {
        "nombre": "Código Corto (12 caracteres: XXXX-XXXX-XXXX)",
        "regex": re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}\b"),
    },
}

# Configuración de Tesseract (PSM 6: bloque uniforme de texto, solo mayúsculas, números y guion)
TESSERACT_CONFIG = (
    "--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
)


# ==============================================================================
# UTILIDADES DE SISTEMA Y TESSERACT
# ==============================================================================
def configurar_tesseract() -> None:
    """Verifica y configura la ruta del binario de Tesseract OCR en Windows."""
    if shutil.which("tesseract"):
        return

    for path in TESSERACT_PATHS:
        if os.path.isfile(path):
            pytesseract.pytesseract.tesseract_cmd = path
            return

    print("\n[ADVERTENCIA] No se encontró 'tesseract.exe' en el PATH ni en las rutas estándar.")
    ruta_manual = input(
        "Introduce la ruta completa a tesseract.exe (o presiona Enter para intentar continuar): "
    ).strip().strip('"')
    if ruta_manual and os.path.isfile(ruta_manual):
        pytesseract.pytesseract.tesseract_cmd = ruta_manual


def encontrar_ejecutable_chrome() -> Optional[str]:
    """Busca el ejecutable de Google Chrome en las rutas estándar de Windows."""
    rutas = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for r in rutas:
        if os.path.isfile(r):
            return r
    return None


def lanzar_chrome_cdp() -> bool:
    """Lanza una instancia de Chrome con el puerto de depuración 9222 habilitado."""
    chrome_exe = encontrar_ejecutable_chrome()
    comando_exacto = (
        f'"{chrome_exe or "chrome.exe"}" '
        f'--remote-debugging-port=9222 '
        f'--user-data-dir="{CHROME_PROFILE_DIR}" '
        f'"https://www.xbox.com/redeem" "https://www.twitch.tv"'
    )

    print("\n" + "=" * 70)
    print("[ERROR DE CONEXIÓN CDP] No se detectó Chrome en http://localhost:9222")
    print("=" * 70)
    print("Para que el Sniper funcione, Chrome debe abrirse con este comando:")
    print(f"\n    {comando_exacto}\n")

    opcion = input("¿Deseas que el script lance Chrome automáticamente ahora? (S/n): ").strip().lower()
    if opcion in ("", "s", "si", "sí", "y", "yes"):
        if not chrome_exe:
            print("[ERROR] No se encontró chrome.exe automáticamente. Ejecuta el comando manualmente.")
            return False

        os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)
        subprocess.Popen(
            [
                chrome_exe,
                "--remote-debugging-port=9222",
                f"--user-data-dir={CHROME_PROFILE_DIR}",
                "https://www.xbox.com/redeem",
                "https://www.twitch.tv",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("[INFO] Chrome lanzado. Esperando 4 segundos para inicializar CDP...")
        time.sleep(4)
        return True

    return False


# ==============================================================================
# CONEXIÓN CDP Y LOCALIZACIÓN DEL DOM / IFRAME DE XBOX
# ==============================================================================
def conectar_navegador(pw: Playwright) -> Browser:
    """Conecta Playwright a la sesión de Chrome mediante CDP en localhost:9222."""
    while True:
        try:
            browser = pw.chromium.connect_over_cdp(CDP_URL)
            print(f"[OK] Conectado exitosamente a Chrome vía CDP ({CDP_URL}).")
            return browser
        except Exception:
            if not lanzar_chrome_cdp():
                print("[SALIDA] Cierra todas las ventanas de Chrome o usa iniciar_chrome_sniper.bat.")
                sys.exit(1)


def localizar_input_xbox(browser: Browser) -> Tuple[Optional[Page], Optional[Frame], Optional[Locator]]:
    """
    Itera sobre todos los contexts, pages y frames para encontrar el <input> de canje.
    Prioriza los frames de 'redeem.microsoft.com' o páginas de 'xbox.com/redeem'.
    """
    candidatos_frames = []

    for context in browser.contexts:
        for page in context.pages:
            url_page = (page.url or "").lower()
            # Recolectar todos los frames de la página
            for frame in page.frames:
                url_frame = (frame.url or "").lower()
                # Prioridad alta si la URL del frame o de la página pertenece a redeem / xbox
                prioridad = 0
                if "redeem.microsoft.com" in url_frame:
                    prioridad = 3
                elif "xbox.com" in url_page and ("redeem" in url_page or "redeem" in url_frame):
                    prioridad = 2
                elif "microsoft.com" in url_frame or "xbox.com" in url_frame:
                    prioridad = 1

                if prioridad > 0:
                    candidatos_frames.append((prioridad, page, frame))

    # Ordenar por mayor prioridad primero (primero el iframe redeem.microsoft.com)
    candidatos_frames.sort(key=lambda x: x[0], reverse=True)

    # Buscar los selectores específicos en los frames candidatos
    for _, page, frame in candidatos_frames:
        for selector in INPUT_SELECTORS:
            try:
                loc = frame.locator(selector).first
                if loc.count() > 0 and loc.is_visible():
                    return page, frame, loc
            except Exception:
                continue

    return None, None, None


def inyectar_y_confirmar(
    page: Page, frame: Frame, input_locator: Locator, codigo: str
) -> bool:
    """
    Inyecta el código directamente en el DOM usando .fill() y ejecuta un intento
    automático de pulsar el botón de confirmación tan pronto como se habilite.
    """
    try:
        # 1. Inyección directa en el input (dispara eventos input/change de React)
        input_locator.fill(codigo, timeout=1500)

        # 2. Traer la pestaña de Xbox al frente inmediatamente tras escribir el código
        try:
            page.bring_to_front()
        except Exception:
            pass

        # 3. Intento rápido no bloqueante de auto-confirmación (polling corto de ~1.2s
        #    mientras el backend de Microsoft valida los 25 caracteres y habilita el botón)
        t_inicio = time.perf_counter()
        confirmado = False
        while (time.perf_counter() - t_inicio) < 1.2:
            for btn_selector in CONFIRM_BUTTON_SELECTORS:
                try:
                    btn = frame.locator(btn_selector).first
                    if btn.count() > 0 and btn.is_visible() and btn.is_enabled():
                        btn.click(timeout=300, no_wait_after=True)
                        confirmado = True
                        break
                except Exception:
                    continue
            if confirmado:
                break
            time.sleep(0.04)

        return True
    except Exception as exc:
        print(f"\n[ERROR DOM] Falló la inyección del código {codigo}: {exc}")
        return False


# ==============================================================================
# CALIBRACIÓN DE REGIÓN DE CAPTURA (PERSISTENTE)
# ==============================================================================
def esperar_tecla_calibracion() -> None:
    """Espera a que el usuario presione X o F8 (compatible con laptops Dell sin usar Fn)."""
    while True:
        if keyboard.is_pressed("x") or keyboard.is_pressed("F8"):
            break
        time.sleep(0.02)


def calibrar_region() -> dict:
    """
    Solicita al usuario posicionar el cursor en la esquina superior izquierda (X o F8)
    e inferior derecha (X o F8) del área donde aparece el código en el stream.
    """
    print("\n" + "=" * 70)
    print("   MODO CALIBRACIÓN DE ZONA DEL STREAM")
    print("=" * 70)
    print("1. Coloca el cursor en la ESQUINA SUPERIOR IZQUIERDA del código y presiona [X] (o Fn+F8).")

    esperar_tecla_calibracion()
    x1, y1 = pyautogui.position()
    winsound.Beep(1000, 150)
    print(f"   -> Esquina Superior Izquierda registrada: X={x1}, Y={y1}")
    time.sleep(0.45)  # Debounce para evitar doble lectura

    print("2. Coloca el cursor en la ESQUINA INFERIOR DERECHA del código y presiona [X] (o Fn+F8).")
    esperar_tecla_calibracion()
    x2, y2 = pyautogui.position()
    winsound.Beep(1300, 150)
    print(f"   -> Esquina Inferior Derecha registrada:   X={x2}, Y={y2}")
    time.sleep(0.45)

    left = int(min(x1, x2))
    top = int(min(y1, y2))
    width = max(10, int(abs(x2 - x1)))
    height = max(10, int(abs(y2 - y1)))

    region = {"top": top, "left": left, "width": width, "height": height}

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(region, f, indent=4)

    print(f"[OK] Configuración guardada en '{CONFIG_FILE}': {region}\n")
    return region


def cargar_o_calibrar_region() -> dict:
    """Carga la región desde config_cdp.json si existe y es válida; si no, calibra."""
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if all(k in data for k in ("top", "left", "width", "height")):
                if data["width"] > 0 and data["height"] > 0:
                    print(f"[OK] Región cargada desde '{CONFIG_FILE}': {data}")
                    return {
                        "top": int(data["top"]),
                        "left": int(data["left"]),
                        "width": int(data["width"]),
                        "height": int(data["height"]),
                    }
        except Exception as exc:
            print(f"[ADVERTENCIA] Archivo '{CONFIG_FILE}' corrupto ({exc}). Se recalibrará.")

    return calibrar_region()


# ==============================================================================
# PIPELINE DE VISIÓN ARTIFICIAL Y OCR
# ==============================================================================
def preprocesar_frame(img_bgra: np.ndarray) -> np.ndarray:
    """
    Convierte captura BGRA de mss a escala de grises, escala 1.5x y aplica
    binarización adaptativa Otsu (THRESH_BINARY + THRESH_OTSU).
    """
    gris = cv2.cvtColor(img_bgra, cv2.COLOR_BGRA2GRAY)
    escalada = cv2.resize(
        gris, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC
    )
    _, binarizada = cv2.threshold(
        escalada, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    return binarizada


def guardar_codigo_cazado(codigo: str) -> None:
    """Registra el código detectado junto con la marca de tiempo en codigos_cazados.txt."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    linea = f"[{timestamp}] {codigo}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(linea)


# ==============================================================================
# MENÚ Y BUCLE PRINCIPAL DE BAJA LATENCIA
# ==============================================================================
def seleccionar_patron() -> re.Pattern:
    """Permite al usuario elegir el patrón Regex al inicio."""
    print("\n" + "=" * 70)
    print("   SELECCIÓN DE FORMATO DE CÓDIGO OBJETIVO")
    print("=" * 70)
    for clave, info in REGEX_PATTERNS.items():
        print(f"  [{clave}] {info['nombre']}")

    eleccion = input("\nElige una opción (1 o 2) [Por defecto: 1]: ").strip()
    if eleccion not in REGEX_PATTERNS:
        eleccion = "1"

    seleccion = REGEX_PATTERNS[eleccion]
    print(f"[OK] Usando patrón: {seleccion['nombre']}\n")
    return seleccion["regex"]


def main() -> None:
    os.system("cls" if os.name == "nt" else "clear")
    print("=" * 70)
    print("   XBOX DIRECT DOM CODE SNIPER - CDP LOW-LATENCY EDITION")
    print("=" * 70)

    configurar_tesseract()
    patron_regex = seleccionar_patron()
    region = cargar_o_calibrar_region()

    codigos_usados: set[str] = set()
    pausado = False
    debug_ocr = False
    ventana_debug_abierta = False

    # Estado de los atajos de teclado con debounce simple
    ultimo_f7 = 0.0
    ultimo_f9 = 0.0
    ultimo_f10 = 0.0

    with sync_playwright() as pw:
        browser = conectar_navegador(pw)
        page_xbox, frame_xbox, input_locator = localizar_input_xbox(browser)

        if input_locator is None:
            print(
                "\n[AVISO] Aún no se detecta el <input> de canje en xbox.com/redeem."
            )
            print(
                "        Asegúrate de haber iniciado sesión en Microsoft y estar en la página de canje."
            )
            print(
                "        El script buscará el iframe automáticamente en segundo plano.\n"
            )
        else:
            print("[OK] Iframe e <input> de canje de Xbox localizados y listos para inyección DOM.\n")

        print("CONTROLES EN CALIENTE (compatibles con laptop sin tecla Fn):")
        print("  [F7]  o [Ctrl+1] Pausar / Reanudar escaneo OCR")
        print("  [F9]  o [Ctrl+2] Recalibrar coordenadas de la zona del stream")
        print("  [F10] o [Ctrl+3] Mostrar / Ocultar ventana Debug de visión OCR en vivo")
        print("  [ESC]            Salir del programa en cualquier momento")
        print("-" * 70)

        ultimo_chequeo_dom = 0.0
        dom_conectado = input_locator is not None

        # Contadores para cálculo de FPS reales
        frames_contados = 0
        t_fps = time.perf_counter()
        fps_actuales = 0.0

        with mss.mss() as sct:
            try:
                while True:
                    ahora = time.perf_counter()

                    # --- Salir con ESC ---
                    if keyboard.is_pressed("esc"):
                        print("\n\n[INFO] Saliendo de Xbox Direct DOM Code Sniper...")
                        break

                    # --- Hotkey F7 o Ctrl+1: Pausar / Reanudar ---
                    if (keyboard.is_pressed("F7") or keyboard.is_pressed("ctrl+1")) and (ahora - ultimo_f7) > 0.35:
                        pausado = not pausado
                        ultimo_f7 = ahora
                        winsound.Beep(600 if pausado else 900, 120)

                    # --- Hotkey F9 o Ctrl+2: Recalibrar Región ---
                    if (keyboard.is_pressed("F9") or keyboard.is_pressed("ctrl+2")) and (ahora - ultimo_f9) > 0.35:
                        ultimo_f9 = ahora
                        if ventana_debug_abierta:
                            cv2.destroyAllWindows()
                            ventana_debug_abierta = False
                        region = calibrar_region()
                        t_fps = time.perf_counter()
                        frames_contados = 0

                    # --- Hotkey F10 o Ctrl+3: Alternar vista Debug OpenCV ---
                    if (keyboard.is_pressed("F10") or keyboard.is_pressed("ctrl+3")) and (ahora - ultimo_f10) > 0.35:
                        debug_ocr = not debug_ocr
                        ultimo_f10 = ahora
                        if not debug_ocr and ventana_debug_abierta:
                            cv2.destroyAllWindows()
                            ventana_debug_abierta = False

                    # --- Re-verificar conexión con el iframe de Xbox cada 2 segundos ---
                    if (ahora - ultimo_chequeo_dom) > 2.0:
                        ultimo_chequeo_dom = ahora
                        try:
                            if (
                                input_locator is None
                                or frame_xbox is None
                                or frame_xbox.is_detached()
                                or input_locator.count() == 0
                            ):
                                page_xbox, frame_xbox, input_locator = localizar_input_xbox(
                                    browser
                                )
                            dom_conectado = input_locator is not None
                        except Exception:
                            page_xbox, frame_xbox, input_locator = localizar_input_xbox(
                                browser
                            )
                            dom_conectado = input_locator is not None

                    # --- Si está en pausa, actualizar telemetría y esperar ---
                    if pausado:
                        estado_dom = "CONECTADO" if dom_conectado else "BUSCANDO IFRAME..."
                        sys.stdout.write(
                            f"\r[PAUSADO con F7] | FPS:  0.0 | Iframe Xbox: {estado_dom} | Cazados: {len(codigos_usados)}   "
                        )
                        sys.stdout.flush()
                        time.sleep(0.05)
                        continue

                    # --- 1. Captura ultra-rápida con MSS ---
                    sct_img = sct.grab(region)
                    frame_np = np.array(sct_img)

                    # --- 2. Preprocesamiento con OpenCV (Grises + 1.5x + Otsu) ---
                    procesada = preprocesar_frame(frame_np)

                    # --- 3. Ventana Debug en vivo (F10) ---
                    if debug_ocr:
                        cv2.imshow("Xbox Sniper - Vista OCR (Otsu 1.5x)", procesada)
                        cv2.waitKey(1)
                        ventana_debug_abierta = True

                    # --- 4. Extracción de texto con Tesseract OCR ---
                    try:
                        texto_ocr = pytesseract.image_to_string(
                            procesada, config=TESSERACT_CONFIG
                        )
                    except pytesseract.TesseractNotFoundError:
                        print(
                            "\n[ERROR CRÍTICO] Tesseract-OCR no está instalado o no se encuentra su ejecutable."
                        )
                        break
                    except Exception:
                        texto_ocr = ""

                    # Normalizar saltos de línea o espacios accidentales alrededor de guiones
                    texto_limpio = texto_ocr.upper().strip()

                    # --- 5. Detección por Regex e Inyección Directa en DOM ---
                    coincidencias = patron_regex.findall(texto_limpio)
                    for codigo in coincidencias:
                        if codigo not in codigos_usados:
                            codigos_usados.add(codigo)
                            t_detect = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                            print(
                                f"\n\n[¡CÓDIGO DETECTADO! {t_detect}] >>> {codigo} <<<"
                            )

                            # Asegurar referencia fresca al input si aún no estaba listo
                            if input_locator is None or frame_xbox is None:
                                page_xbox, frame_xbox, input_locator = (
                                    localizar_input_xbox(browser)
                                )

                            if (
                                page_xbox is not None
                                and frame_xbox is not None
                                and input_locator is not None
                            ):
                                exito = inyectar_y_confirmar(
                                    page_xbox, frame_xbox, input_locator, codigo
                                )
                                if exito:
                                    print(
                                        f"[DOM INJECT OK] Código '{codigo}' inyectado en xbox.com/redeem y enviado."
                                    )
                            else:
                                print(
                                    f"[ADVERTENCIA] No se encontró el iframe de Xbox abierto para inyectar '{codigo}'."
                                )

                            # Alerta sonora y registro en disco
                            winsound.Beep(1500, 400)
                            guardar_codigo_cazado(codigo)

                    # --- 6. Telemetría en tiempo real en una sola línea ---
                    frames_contados += 1
                    elapsed_fps = time.perf_counter() - t_fps
                    if elapsed_fps >= 0.5:
                        fps_actuales = frames_contados / elapsed_fps
                        frames_contados = 0
                        t_fps = time.perf_counter()

                    estado_dom = "CONECTADO" if dom_conectado else "BUSCANDO IFRAME..."
                    estado_debug = "ON" if debug_ocr else "OFF"
                    sys.stdout.write(
                        f"\r[ACTIVO] | FPS: {fps_actuales:5.1f} | Iframe Xbox: {estado_dom} | Debug(F10): {estado_debug} | Cazados: {len(codigos_usados)}   "
                    )
                    sys.stdout.flush()

            except KeyboardInterrupt:
                print("\n\n[INFO] Interrupción recibida. Cerrando Sniper...")
            finally:
                if ventana_debug_abierta:
                    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
