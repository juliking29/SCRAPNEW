import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service # <--- AÑADIDO
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import traceback
import re
from dateutil.parser import parse
import uvicorn
import os # <--- AÑADIDO

app = FastAPI()

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Helper Functions (Combined and Deduplicated) ---
def init_driver():
    """Initialize Chrome WebDriver in headless mode with improved error handling"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920x1080')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    # MODIFICACIÓN PARA RAILWAY Y ENTORNOS SIMILARES
    chrome_binary_path = os.environ.get("GOOGLE_CHROME_BIN")
    chromedriver_path = os.environ.get("CHROMEDRIVER_PATH")

    if chrome_binary_path:
        chrome_options.binary_location = chrome_binary_path
        print(f"Usando Chrome binary de: {chrome_binary_path}")
    else:
        print("Advertencia: GOOGLE_CHROME_BIN no está configurado. Selenium intentará usar la ubicación por defecto de Chrome.")

    try:
        if chromedriver_path:
            print(f"Usando ChromeDriver de: {chromedriver_path}")
            service = Service(executable_path=chromedriver_path)
            driver = webdriver.Chrome(service=service, options=chrome_options)
        else:
            print("Advertencia: CHROMEDRIVER_PATH no está configurado. Selenium intentará encontrar ChromeDriver en el PATH.")
            # Si no se especifica chromedriver_path, Selenium intentará encontrarlo en el PATH del sistema.
            # Esto podría no funcionar en Railway si no está configurado correctamente.
            driver = webdriver.Chrome(options=chrome_options)
        print("WebDriver inicializado correctamente.")
        return driver
    except Exception as e:
        print(f"Error initializing ChromeDriver: {str(e)}")
        print(traceback.format_exc())
        # Intenta capturar más información sobre el error específico de WebDriver si es posible
        if "failed to start browser" in str(e).lower() or "cannot find chrome binary" in str(e).lower():
            print("Detalle del error: Parece que el binario de Chrome no se encuentra o no se puede iniciar.")
            print(f"  GOOGLE_CHROME_BIN: {os.environ.get('GOOGLE_CHROME_BIN')}")
            print(f"  CHROMEDRIVER_PATH: {os.environ.get('CHROMEDRIVER_PATH')}")
            print(f"  chrome_options.binary_location: {chrome_options.binary_location if hasattr(chrome_options, 'binary_location') else 'No establecida'}")
        elif "unable to discover open window in chrome" in str(e).lower():
            print("Detalle del error: ChromeDriver se inició pero no pudo conectarse a una ventana de Chrome. Podría ser un problema con --headless o el entorno gráfico.")
        return None

def clean_odd_value(odd_text):
    """Clean and standardize odd values"""
    if not odd_text:
        return "N/A"
    
    odd_text = odd_text.strip().replace('\xa0', ' ').replace('\u00a0', ' ')
    
    match = re.search(r'(\d+\.?\d*)', odd_text)
    if match:
        return match.group(1)
    
    return odd_text

def parse_match_date_liga(date_str): # Renamed to avoid conflict, specific to La Liga scraper
    """Parse match date into a datetime object for La Liga scraper"""
    if not date_str:
        return "N/A"
    
    try:
        date_part = date_str.split('-')[0].strip() # Remove time part
        return parse(date_part, dayfirst=True).strftime('%Y-%m-%d %H:%M')
    except Exception as e:
        print(f"Error parsing date (liga): {date_str} - {str(e)}")
        return date_str

def parse_match_date_transfermarkt_general(date_str): # Renamed, specific to general Transfermarkt odds
    """Parse match date into a datetime object for general Transfermarkt odds"""
    try:
        # Get current date and year
        today = datetime.now()
        return parse(date_str).strftime('%Y-%m-%d %H:%M')
    except Exception as e:
        print(f"Error parsing date (transfermarkt general): {date_str} - {str(e)}")
        return date_str

def safe_get_text(element, default="N/A"):
    """Safely get text from BeautifulSoup element"""
    if element is None:
        return default
    try:
        return element.get_text(strip=True)
    except:
        return default

def parse_relevo_date(date_str):
    """Parse Relevo's article date into a datetime object or return original."""
    if not date_str:
        return "N/A"
    try:
        return parse(date_str).strftime('%Y-%m-%d %H:%M:%S')
    except Exception as e:
        print(f"Error parsing date (relevo): {date_str} - {str(e)}")
        return date_str

# --- Scraper 1: La Liga Odds ---
def scrape_liga_odds():
    """Scraping function for La Liga odds page"""
    print("Iniciando scrape_liga_odds...")
    driver = init_driver()
    if not driver:
        print("scrape_liga_odds: Fallo al inicializar el driver.")
        return {"error": "Failed to initialize browser"}
    
    url = "https://www.transfermarkt.es/apuestas/la-liga/"
    print(f"Accediendo a Cuotas La Liga: {url}")
    
    result = {
        "scraped_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "matches": [],
        "title_odds": [],
        "combined_bet": {}
    }
    
    try:
        driver.get(url)
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CLASS_NAME, "oddscomp-widget-iframe-container"))
            )
            print("Cuotas La Liga: Contenido principal cargado")
        except Exception as e:
            print(f"Cuotas La Liga: Advertencia de carga de contenido: {str(e)}")
        
        time.sleep(3) # Espera adicional para asegurar que todo el JS se ejecute
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        combined_bet_section = soup.find('h2', string='Apuesta combinada de la jornada')
        if combined_bet_section:
            combined_bet = {
                "description": "",
                "bets": []
            }
            desc_paragraphs = []
            next_elem = combined_bet_section.find_next_sibling('p')
            while next_elem and next_elem.name == 'p':
                desc_paragraphs.append(safe_get_text(next_elem))
                next_elem = next_elem.find_next_sibling()
            combined_bet["description"] = " ".join(desc_paragraphs)
            
            # Intentar encontrar las apuestas de forma más robusta si la estructura es variable
            bet_container = combined_bet_section.find_parent() # o un ancestro más específico si es posible
            if bet_container:
                # Buscar párrafos que parezcan ser apuestas dentro del contenedor de la apuesta combinada
                potential_bets_p = bet_container.find_all('p')
                parsed_bets_count = 0
                for p_tag in potential_bets_p:
                    if parsed_bets_count >= 3: # Limitar a 3 apuestas si es necesario
                        break
                    p_text = safe_get_text(p_tag)
                    if ':' in p_text and any(team_keyword in p_text for team_keyword in ['Girona', 'Atlético', 'Barcelona', 'Real Madrid', 'vs']): # Heurística para identificar una línea de apuesta
                        strong_tag = p_tag.find('strong') # Buscar el strong dentro del mismo p
                        if not strong_tag: # A veces el strong puede estar anidado
                           strong_tag = p_tag.find_next('strong') # O ser el siguiente

                        odd_value = "N/A"
                        if strong_tag:
                            odd_value = clean_odd_value(safe_get_text(strong_tag))
                        
                        parts = p_text.split(':', 1) # Dividir solo en el primer ':'
                        match_part = parts[0].strip()
                        bet_part = parts[1].split(odd_value)[0].strip() if len(parts) > 1 and odd_value != "N/A" else (parts[1].strip() if len(parts) > 1 else "N/A")


                        combined_bet["bets"].append({
                            "match": match_part,
                            "bet": bet_part,
                            "odd": odd_value
                        })
                        parsed_bets_count +=1
            result["combined_bet"] = combined_bet
        else:
            print("Cuotas La Liga: Sección 'Apuesta combinada de la jornada' no encontrada.")

        
        match_table = soup.find('figure', class_='wp-block-table') # Asume que es la primera tabla de este tipo
        if match_table:
            table = match_table.find('table')
            if table:
                rows = table.find_all('tr')[1:] # Omitir encabezado
                for row in rows:
                    try:
                        cols = row.find_all('td')
                        if len(cols) >= 4:
                            prediction_text = safe_get_text(cols[3])
                            prediction_parts = prediction_text.split('➡') # o '→' si el caracter es diferente
                            match_data = {
                                "teams": safe_get_text(cols[0]),
                                "date": parse_match_date_liga(safe_get_text(cols[1])),
                                "stadium": safe_get_text(cols[2]),
                                "prediction": prediction_parts[0].strip() if prediction_parts else "N/A",
                                "odd": clean_odd_value(prediction_parts[-1].strip() if len(prediction_parts) > 1 else (prediction_parts[0].strip() if prediction_parts and not prediction_parts[0].endswith(prediction_parts[0].strip()) else "N/A"))
                            }
                            result["matches"].append(match_data)
                    except Exception as e:
                        print(f"Error procesando fila de partido de La Liga: {str(e)}")
                        continue
            else:
                print("Cuotas La Liga: Tabla de partidos (<table>) no encontrada dentro de <figure class='wp-block-table'>.")
        else:
            print("Cuotas La Liga: Contenedor de tabla de partidos (<figure class='wp-block-table'>) no encontrado.")

        
        title_section = soup.find(lambda tag: tag.name and "Favoritos para ganar la liga española" in tag.get_text())
        if title_section:
            title_table_figure = title_section.find_next('figure', class_='wp-block-table')
            if title_table_figure:
                table = title_table_figure.find('table')
                if table:
                    headers = []
                    thead = table.find('thead')
                    if thead:
                        headers = [safe_get_text(th) for th in thead.find_all('th')]
                    
                    tbody_rows = table.find('tbody').find_all('tr') if table.find('tbody') else table.find_all('tr')[1:] # Fallback si no hay tbody explícito

                    for row in tbody_rows:
                        cols = row.find_all('td')
                        if len(cols) > 0 and (not headers or len(cols) == len(headers)): # Asegurar que hay columnas y coinciden con headers si existen
                            team_data = {"team": safe_get_text(cols[0])}
                            if headers: # Si tenemos encabezados, usarlos
                                for i in range(1, min(len(headers), len(cols))):
                                    team_data[headers[i]] = clean_odd_value(safe_get_text(cols[i]))
                            else: # Si no hay encabezados, usar nombres genéricos o inferir
                                for i in range(1, len(cols)):
                                     team_data[f"Bookmaker_{i}"] = clean_odd_value(safe_get_text(cols[i]))
                            result["title_odds"].append(team_data)
                else:
                    print("Cuotas La Liga: Tabla de favoritos (<table>) no encontrada dentro de la figura.")
            else:
                print("Cuotas La Liga: Contenedor (<figure class='wp-block-table'>) para tabla de favoritos no encontrado después de la sección.")
        else:
            print("Cuotas La Liga: Sección 'Favoritos para ganar la liga española' no encontrada.")
            
    except Exception as e:
        print(f"Error durante el scraping de cuotas de La Liga: {str(e)}")
        print(traceback.format_exc())
        try:
            # Guardar información de depuración si es posible
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            driver.save_screenshot(f"error_screenshot_liga_{timestamp}.png")
            with open(f"error_page_source_liga_{timestamp}.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("Cuotas La Liga: Archivos de depuración guardados")
        except Exception as e_debug:
            print(f"Cuotas La Liga: No se pudieron guardar archivos de depuración: {e_debug}")
        result["error_scraping"] = str(e) # Añadir error al resultado para el endpoint
        result["stack_trace_scraping"] = traceback.format_exc()

    finally:
        if driver:
            driver.quit()
            print("Cuotas La Liga: WebDriver cerrado.")
    
    print(f"scrape_liga_odds finalizado. Resultado: {json.dumps(result, indent=2, ensure_ascii=False)}")
    return result

# --- Scraper 2: Relevo News ---
def scrape_relevo_news():
    """Scraping function for Relevo news page."""
    print("Iniciando scrape_relevo_news...")
    driver = init_driver()
    if not driver:
        print("scrape_relevo_news: Fallo al inicializar el driver.")
        return {"error": "Failed to initialize browser"}
    
    url = "https://www.relevo.com/futbol/mercado-fichajes/"
    print(f"Accediendo a Noticias Relevo: {url}")
    
    result = {
        "scraped_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "articles": []
    }
    
    try:
        driver.get(url)
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.grid--AB-C article.article"))
            )
            print("Noticias Relevo: Contenido principal cargado")
        except Exception as e:
            print(f"Noticias Relevo: Advertencia de carga de contenido: {str(e)}")
        
        time.sleep(5) # Espera para JS
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        articles_html = soup.select("div.grid--AB-C div.grid__col article.article") # Selector más específico si es necesario
        
        if not articles_html:
            print("Noticias Relevo: No se encontraron artículos. Revisa selectores o estructura de la página.")
            # Intenta guardar el HTML para depuración
            try:
                with open("relevo_no_articles_page.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print("Noticias Relevo: HTML de página sin artículos guardado.")
            except: pass


        for article_tag in articles_html:
            try:
                title_tag = article_tag.find('h2', class_='article__title') # o h3, etc.
                title = "N/A"
                link = "N/A"
                
                if title_tag and title_tag.find('a'):
                    title_anchor = title_tag.find('a')
                    title = safe_get_text(title_anchor)
                    link_href = title_anchor.get('href', "N/A")
                    if link_href and not link_href.startswith('http'):
                        link = "https://www.relevo.com" + link_href
                    else:
                        link = link_href

                authors_list = []
                author_section = article_tag.find('div', class_='author--art') # o similar
                if author_section:
                    # Primero, intentar con la estructura más específica
                    author_signature = author_section.find('p', class_='author__signature') # O el tag que contenga los nombres
                    if author_signature:
                        author_tags_a = author_signature.find_all('a')
                        if author_tags_a:
                            for author_a in author_tags_a:
                                author_name = safe_get_text(author_a)
                                author_url = author_a.get('href', "N/A")
                                if author_url and not author_url.startswith('http'):
                                    author_url = "https://www.relevo.com" + author_url
                                authors_list.append({
                                    "name": author_name,
                                    "profile_url": author_url
                                })
                        else: # Si no hay <a>, tomar el texto del <p>
                            full_signature_text = safe_get_text(author_signature)
                            # Eliminar la parte de la fecha si está presente (ej. "Juan Pérez Hace 2 horas")
                            author_name_candidate = full_signature_text.split("Hace")[0].strip()
                            if author_name_candidate: # Asegurarse que no sea solo espacios
                                authors_list.append({"name": author_name_candidate, "profile_url": "N/A"})
                    
                    # Si no se encontraron autores con la firma, buscar directamente en la sección de autor
                    if not authors_list:
                        all_author_links = author_section.find_all('a', href_re=re.compile(r'/autor/'))
                        for author_link_tag in all_author_links:
                            authors_list.append({
                                "name": safe_get_text(author_link_tag),
                                "profile_url": "https://www.relevo.com" + author_link_tag.get('href') if author_link_tag.get('href') else "N/A"
                            })


                publication_date_str = "N/A"
                date_tag = None
                if author_section : # La fecha suele estar cerca del autor
                    date_tag = author_section.find('time', class_='author__date')
                
                # Si no se encuentra con la clase específica, buscar cualquier tag <time> dentro del artículo
                if not date_tag:
                    date_tag = article_tag.find('time')

                if date_tag:
                    if date_tag.has_attr('datetime'):
                        publication_date_str = date_tag['datetime']
                    else:
                        publication_date_str = safe_get_text(date_tag) # Tomar el texto visible
                publication_date = parse_relevo_date(publication_date_str)

                image_url = "N/A"
                img_container = article_tag.find('div', class_='article__container-img') # o 'figure', 'picture'
                if img_container:
                    img_tag = img_container.find('img')
                    if img_tag:
                        image_url = img_tag.get('src', img_tag.get('data-src', "N/A")) # Comprobar src y data-src para lazy loading

                article_data = {
                    "title": title,
                    "link": link,
                    "authors": authors_list if authors_list else [{"name": "N/A", "profile_url": "N/A"}],
                    "publication_date_iso": publication_date if publication_date != "N/A" else publication_date_str,
                    "image_url": image_url
                }
                result["articles"].append(article_data)
            except Exception as e:
                print(f"Error procesando un artículo de Relevo: {str(e)}")
                print(traceback.format_exc())
                continue # Continuar con el siguiente artículo
            
    except Exception as e:
        print(f"Error durante el scraping de noticias de Relevo: {str(e)}")
        print(traceback.format_exc())
        error_filename_detail = datetime.now().strftime('%Y%m%d_%H%M%S')
        try:
            driver.save_screenshot(f"error_screenshot_relevo_{error_filename_detail}.png")
            with open(f"error_page_source_relevo_{error_filename_detail}.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("Noticias Relevo: Archivos de depuración guardados")
        except Exception as e_debug:
            print(f"Noticias Relevo: No se pudieron guardar los archivos de depuración: {e_debug}")
        result["error_scraping"] = str(e)
        result["stack_trace_scraping"] = traceback.format_exc()
    finally:
        if driver:
            driver.quit()
            print("Noticias Relevo: WebDriver cerrado.")
    
    print(f"scrape_relevo_news finalizado. Resultado: {json.dumps(result, indent=2, ensure_ascii=False)}")
    return result

# --- Scraper 3: TablesLeague Data ---
def scrape_tablesleague_data():
    """
    Función principal para hacer scraping de las tablas de ligas de m.tablesleague.com
    """
    url = "https://m.tablesleague.com/"
    print(f"Accediendo a TablesLeague: {url}")
    
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    result = {
        "scraped_at": current_time,
        "leagues": []
    }
    
    try:
        headers = { # User-Agent para evitar bloqueos básicos
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=20) # Timeout aumentado
        response.raise_for_status() # Lanza excepción para errores HTTP
        soup = BeautifulSoup(response.content, 'html.parser')
        
        content_div = soup.find('div', class_='content')
        if not content_div:
            error_msg = "No se encontró el contenedor principal 'div.content'. La estructura del sitio puede haber cambiado."
            print(f"TablesLeague ERROR: {error_msg}")
            result["error"] = error_msg
            return result

        # Encuentra todas las cabeceras de liga que contienen una bandera (img.flag)
        all_league_title_headers = []
        for header_candidate in content_div.find_all('div', class_='header'):
            if header_candidate.find('img', class_='flag'):
                all_league_title_headers.append(header_candidate)
        
        print(f"TablesLeague DEBUG: Encontradas {len(all_league_title_headers)} cabeceras de título de liga potenciales.")
        
        if not all_league_title_headers:
            error_msg = "No se encontraron cabeceras de título de liga con banderas. No se pueden extraer tablas."
            print(f"TablesLeague WARN: {error_msg}")
            result["error"] = error_msg # O "info" si se considera normal que no haya ligas a veces
            return result
            
        for index, league_header_tag in enumerate(all_league_title_headers):
            league_data = {"name": "Unknown League", "teams": []}
            try:
                print(f"TablesLeague DEBUG: Procesando cabecera de liga #{index + 1}")
                
                league_name_text = "Unknown League"
                img_tag = league_header_tag.find('img', class_='flag')
                
                # Intenta obtener el texto después de la imagen de la bandera
                if img_tag and img_tag.next_sibling and isinstance(img_tag.next_sibling, str):
                    league_name_text = img_tag.next_sibling.strip()
                elif league_header_tag.find('a'): # A veces el nombre está en un <a>
                    league_name_text = safe_get_text(league_header_tag.find('a'))
                elif league_header_tag.contents: # Como fallback, tomar el último string no vacío
                    for content_item in reversed(league_header_tag.contents):
                        if isinstance(content_item, str) and content_item.strip():
                            league_name_text = content_item.strip()
                            break
                
                # Si aún es "Unknown League", tomar todo el texto del header y limpiar el alt de la imagen
                if league_name_text == "Unknown League" or not league_name_text.strip():
                    full_header_text = league_header_tag.get_text(separator=" ", strip=True)
                    img_alt = img_tag.get('alt', '') if img_tag else ''
                    league_name_text = full_header_text.replace(img_alt, '').strip()

                league_data["name"] = league_name_text if league_name_text else "League Name Not Found"
                print(f"TablesLeague DEBUG: Nombre de liga extraído: '{league_data['name']}'")

                table_div = league_header_tag.find_next_sibling('div', class_='table')
                if not table_div:
                    print(f"TablesLeague WARN: No se encontró 'div.table' después de la cabecera para la liga: '{league_data['name']}'. Saltando.")
                    continue
                
                rows = table_div.find_all('div', class_='row')
                if not rows or len(rows) <= 1: # Menos de 1 fila (aparte del header) no es útil
                    print(f"TablesLeague WARN: No se encontraron filas de datos (div.row) para la liga: '{league_data['name']}'.")
                    continue

                column_headers = []
                header_row_tag = table_div.find('div', class_='row headers')
                if header_row_tag:
                    header_cells = header_row_tag.find_all('div', class_='cell')
                    column_headers = [safe_get_text(cell) for cell in header_cells]
                
                if not column_headers: # Fallback si no se encuentran headers explícitos
                    print(f"TablesLeague WARN: No se encontraron encabezados de columna para la liga: '{league_data['name']}'. Usando predeterminados si el número de celdas coincide.")
                    # No estableceremos headers predeterminados aquí, sino que los asignaremos dinámicamente por índice si es necesario.

                for row_tag in rows:
                    if 'headers' in row_tag.get('class', []): # Omitir la fila de encabezados
                        continue 
                    
                    cells = row_tag.find_all('div', class_='cell')
                    if not cells: continue # Omitir filas vacías

                    team_stats = {}
                    for i, cell_tag in enumerate(cells):
                        header_name = column_headers[i] if i < len(column_headers) and column_headers[i] else f"column_{i+1}"
                        # Normalizar nombres de headers comunes
                        raw_header = header_name.upper()
                        if raw_header in ["#", "POS"]: header_name = "Position"
                        elif raw_header in ["TEAM", "CLUB"]: header_name = "Team"
                        elif raw_header in ["M", "P", "PJ", "PLD"]: header_name = "Played"
                        elif raw_header in ["W", "G", "PG"]: header_name = "Won"
                        elif raw_header in ["D", "E", "PE"]: header_name = "Drawn"
                        elif raw_header in ["L", "P", "PP"]: header_name = "Lost" # 'P' es ambiguo, pero Lost es común
                        elif raw_header in ["G+", "GF", "F"]: header_name = "GoalsFor"
                        elif raw_header in ["G-", "GA", "A"]: header_name = "GoalsAgainst"
                        elif raw_header in ["GD", "DG", "DIF"]: header_name = "GoalDifference"
                        elif raw_header in ["PTS", "PUNTOS"]: header_name = "Points"
                        
                        team_stats[header_name] = safe_get_text(cell_tag)
                    
                    # Asegurar que la fila tiene datos mínimos (ej. un nombre de equipo)
                    if team_stats and team_stats.get("Team"): 
                        league_data["teams"].append(team_stats)
                
                if league_data["teams"]:
                    result["leagues"].append(league_data)
                else:
                    print(f"TablesLeague INFO: No se extrajeron equipos válidos para la liga '{league_data['name']}'. No se añadirá.")
            
            except Exception as e_league:
                print(f"TablesLeague ERROR al procesar la liga '{league_data.get('name', 'Desconocida')}' (índice {index}): {str(e_league)}")
                print(traceback.format_exc())
                continue # Continuar con la siguiente liga
    
    except requests.exceptions.RequestException as e_http:
        error_msg = f"Fallo en la petición HTTP a TablesLeague {url}: {str(e_http)}"
        print(f"TablesLeague ERROR: {error_msg}")
        result["error"] = error_msg
        result["stack_trace"] = traceback.format_exc()
    except Exception as e_general:
        error_msg = f"Error inesperado durante el scraping de TablesLeague: {str(e_general)}"
        print(f"TablesLeague ERROR: {error_msg}")
        result["error"] = error_msg
        result["stack_trace"] = traceback.format_exc()
    
    if not result["leagues"] and "error" not in result:
        result["info"] = "El scraping de TablesLeague se completó, pero no se encontraron datos de ligas o no se pudieron procesar."

    print(f"scrape_tablesleague_data finalizado. Ligas encontradas: {len(result.get('leagues', []))}")
    return result


# --- Scraper 4: Transfermarkt General Odds ---
def scrape_transfermarkt_general_odds():
    """Main scraping function for Transfermarkt general odds"""
    print("Iniciando scrape_transfermarkt_general_odds...")
    driver = init_driver()
    if not driver:
        print("scrape_transfermarkt_general_odds: Fallo al inicializar el driver.")
        return {"error": "Failed to initialize browser"}
    
    url = "https://www.transfermarkt.es/apuestas/cuotas/"
    print(f"Accediendo a Cuotas Generales Transfermarkt: {url}")
    
    result = {
        "scraped_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "matches": []
    }
    
    try:
        driver.get(url)
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CLASS_NAME, "card__item-container")) # Esperar a que las tarjetas de partidos estén presentes
            )
            print("Cuotas Generales Transfermarkt: Contenido principal (tarjetas) cargado")
        except Exception as e:
            print(f"Cuotas Generales Transfermarkt: Advertencia de carga de contenido (tarjetas): {str(e)}")
        
        time.sleep(3) # Espera adicional
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        match_cards = soup.find_all('div', class_='card__item-container')
        print(f"Encontrados {len(match_cards)} tarjetas de partidos generales en Transfermarkt")
        
        if not match_cards:
            print("Cuotas Generales Transfermarkt: No se encontraron tarjetas de partidos.")
            # Guardar HTML para depuración si no se encuentran tarjetas
            try:
                with open("transfermarkt_general_no_cards.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print("Cuotas Generales Transfermarkt: HTML de página sin tarjetas guardado.")
            except: pass
            result["info"] = "No se encontraron partidos generales en Transfermarkt en esta ocasión."
            # No retornar error aquí, podría ser que simplemente no hay cuotas destacadas en ese momento.
            # Si es un error persistente, la ausencia de datos será la señal.

        for card in match_cards:
            try:
                match_name_tag = card.find('div', class_='card__bonus-name') # O la clase que contenga el nombre del partido/apuesta
                match_name = safe_get_text(match_name_tag, "Unknown Match")
                
                # El formato de match_name parece ser "Liga: Equipo1 vs Equipo2 - Tipo de Apuesta - Cuota"
                # Hay que parsearlo con cuidado
                league, home_team, away_team, bet_type, odd_value = "Unknown League", "Unknown HT", "Unknown AT", "Unknown Bet", "N/A"

                parts = match_name.split(' - ')
                if len(parts) >= 2: # Al menos "Algo - Cuota"
                    odd_value = parts[-1] # La cuota es la última parte
                    main_info = ' - '.join(parts[:-1]) # El resto es información principal
                    
                    # Ahora parsear main_info que puede ser "Liga: Eq1 vs Eq2 - TipoApuesta" o "Liga: Eq1 vs Eq2"
                    # O incluso "Eq1 vs Eq2 - TipoApuesta"
                    
                    bet_type_parts = main_info.split(' - ', 1) # Dividir por el último '-' para separar tipo de apuesta
                    if len(bet_type_parts) > 1 and len(bet_type_parts[-1]) < 50 : # Heurística para tipo de apuesta corto
                        bet_type = bet_type_parts[-1].strip()
                        match_info_str = bet_type_parts[0].strip()
                    else:
                        bet_type = "Resultado del partido" # Asumir tipo de apuesta por defecto si no se especifica
                        match_info_str = main_info.strip()

                    # Parsear "Liga: Eq1 vs Eq2" o "Eq1 vs Eq2"
                    league_teams_parts = match_info_str.split(':', 1)
                    if len(league_teams_parts) > 1:
                        league = league_teams_parts[0].strip()
                        teams_str = league_teams_parts[1].strip()
                    else:
                        league = "Unknown League" # O intentar inferir de otro lado si es posible
                        teams_str = match_info_str.strip()
                    
                    teams = [t.strip() for t in teams_str.split('vs')]
                    if len(teams) == 2:
                        home_team = teams[0].strip()
                        away_team = teams[1].strip()
                    elif len(teams) == 1 : # Podría ser un evento individual
                        home_team = teams[0].strip()
                        away_team = "N/A"

                else: # Si el split inicial no dio suficientes partes
                    # Podría ser que la cuota esté dentro del texto o falte información
                    # Intentar encontrar un número decimal al final como cuota
                    num_match = re.search(r'(\d+\.\d+)$', match_name)
                    if num_match:
                        odd_value = num_match.group(1)
                        # El resto es el nombre del partido / tipo de apuesta
                        # Se necesitaría una lógica más compleja aquí si este caso es común
                    # Dejar los valores por defecto si no se puede parsear bien

                bookmaker_img = card.find('img', class_='card__logo') # O la clase del logo de la casa de apuestas
                bookmaker_name = "Unknown Bookmaker"
                bookmaker_logo = "N/A"
                if bookmaker_img:
                    bookmaker_name = bookmaker_img.get('alt', safe_get_text(bookmaker_img, "Unknown Bookmaker")).strip()
                    bookmaker_logo = bookmaker_img.get('src', "N/A")

                expiry_tag = card.find('div', class_='countdown') # O la clase que indica la validez
                expiry_time_str = "N/A"
                if expiry_tag and expiry_tag.has_attr('data-valid-until'):
                     expiry_time_str = expiry_tag['data-valid-until']
                # Convertir expiry_time_str a un formato más estándar si es necesario (ej. ISO)
                # Aquí se asume que ya está en un formato útil o se usa tal cual.

                cleaned_odd = clean_odd_value(odd_value)
                
                offer_link_tag = card.find('a', class_='card__button') # O la clase del botón/enlace de la oferta
                offer_link = "N/A"
                if offer_link_tag and offer_link_tag.has_attr('href'):
                    offer_link = offer_link_tag['href']
                    if not offer_link.startswith('http') and offer_link.startswith('/'):
                        offer_link = "https://www.transfermarkt.es" + offer_link # Completar URL relativa

                match_data = {
                    "league": league,
                    "homeTeam": home_team,
                    "awayTeam": away_team,
                    "betType": bet_type,
                    "odd": cleaned_odd,
                    "bookmaker": {
                        "name": bookmaker_name,
                        "logo": bookmaker_logo
                    },
                    "expiryTime": expiry_time_str, # Considerar parsear a datetime si es necesario
                    "offerLink": offer_link
                }
                result["matches"].append(match_data)
            except Exception as e:
                print(f"Error procesando tarjeta de partido general de Transfermarkt: {str(e)}")
                print(traceback.format_exc())
                continue # Continuar con la siguiente tarjeta
            
    except Exception as e:
        print(f"Error durante el scraping de cuotas generales de Transfermarkt: {str(e)}")
        print(traceback.format_exc())
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            driver.save_screenshot(f"error_screenshot_transfermarkt_general_{timestamp}.png")
            with open(f"error_page_source_transfermarkt_general_{timestamp}.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("Cuotas Generales Transfermarkt: Archivos de depuración guardados")
        except Exception as e_debug:
            print(f"Cuotas Generales Transfermarkt: No se pudieron guardar archivos de depuración: {e_debug}")
        result["error_scraping"] = str(e)
        result["stack_trace_scraping"] = traceback.format_exc()
    finally:
        if driver:
            driver.quit()
            print("Cuotas Generales Transfermarkt: WebDriver cerrado.")
    
    print(f"scrape_transfermarkt_general_odds finalizado. Resultado: {json.dumps(result, indent=2, ensure_ascii=False)}")
    return result

# --- API Endpoints ---
@app.get("/")
def root():
    return {
        "message": "Bienvenido a la API Unificada de Scrapers",
        "rutas_disponibles": [
            "/raspar-cuotas-liga",
            "/raspar-noticias-relevo",
            "/raspar-tablas-liga",
            "/raspar-cuotas-generales-transfermarkt"
        ]
    }

@app.get("/raspar-cuotas-liga")
def endpoint_raspar_cuotas_liga():
    try:
        data = scrape_liga_odds()
        # Si el scraper devuelve un error de inicialización del browser, es un 503 o 500.
        # Si el scraper devuelve un error de scraping pero el browser inició, puede ser un 200 con error en el JSON o 500.
        if "error" in data and data["error"] == "Failed to initialize browser":
             return JSONResponse(content=data, status_code=503) # Service Unavailable
        if "error_scraping" in data: # Error durante el proceso de scraping
            # Podrías decidir si esto es un 500 o un 200 con el error detallado.
            # Por ahora, si hay un error de scraping, lo devolvemos como 500.
            return JSONResponse(content=data, status_code=500)
        return JSONResponse(content=data)
    except Exception as e:
        print("ERROR API ENDPOINT (/raspar-cuotas-liga):", e)
        print(traceback.format_exc())
        return JSONResponse(content={"error": "Error interno del servidor en el endpoint", "details": str(e), "stack_trace": traceback.format_exc()}, status_code=500)

@app.get("/raspar-noticias-relevo")
def endpoint_raspar_noticias_relevo():
    try:
        data = scrape_relevo_news()
        if "error" in data and data["error"] == "Failed to initialize browser":
             return JSONResponse(content=data, status_code=503)
        if "error_scraping" in data:
            return JSONResponse(content=data, status_code=500)
        return JSONResponse(content=data)
    except Exception as e:
        print("ERROR API ENDPOINT (/raspar-noticias-relevo):", e)
        print(traceback.format_exc())
        return JSONResponse(content={"error": "Error interno del servidor en el endpoint", "details": str(e), "stack_trace": traceback.format_exc()}, status_code=500)

@app.get("/raspar-tablas-liga") # Este no usa Selenium, así que el manejo de error es diferente
def endpoint_raspar_tablas_liga():
    try:
        data = scrape_tablesleague_data()
        # Si el scraper devuelve un error (ej. no se encontró div.content, fallo HTTP), puede ser 404 o 500
        if "error" in data:
            status_code = 500 # Por defecto
            if "No se encontró el contenedor principal" in data["error"] or "No se encontraron cabeceras de título" in data["error"]:
                status_code = 404 # Not Found, si la estructura esperada no está
            elif "Fallo en la petición HTTP" in data["error"]:
                status_code = 502 # Bad Gateway, si la fuente externa falla
            return JSONResponse(content=data, status_code=status_code)
        
        # Si "info" está presente y no hay "leagues", podría ser un 200 con información.
        if "info" in data and not data.get("leagues"):
            return JSONResponse(content=data, status_code=200) # O 204 No Content si prefieres no devolver cuerpo
            
        return JSONResponse(content=data)
    except Exception as e:
        print(f"ERROR en endpoint /raspar-tablas-liga: {str(e)}")
        print(traceback.format_exc())
        return JSONResponse(
            content={"error": "Error interno del servidor al procesar la solicitud de tablas de liga.", "details": str(e)},
            status_code=500
        )

@app.get("/raspar-cuotas-generales-transfermarkt")
def endpoint_raspar_cuotas_generales_transfermarkt():
    try:
        data = scrape_transfermarkt_general_odds()
        if "error" in data and data["error"] == "Failed to initialize browser":
             return JSONResponse(content=data, status_code=503)
        if "error_scraping" in data:
            return JSONResponse(content=data, status_code=500)
        return JSONResponse(content=data)
    except Exception as e:
        print("ERROR API ENDPOINT (/raspar-cuotas-generales-transfermarkt):", e)
        print(traceback.format_exc())
        return JSONResponse(content={"error": "Error interno del servidor en el endpoint", "details": str(e), "stack_trace": traceback.format_exc()}, status_code=500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000)) # Railway suele definir PORT
    print(f"Intentando ejecutar el servidor Uvicorn en host 0.0.0.0 y puerto {port}...")
    # En Railway, no necesitas --reload, ya que el ciclo de vida lo maneja Railway.
    uvicorn.run(app, host="0.0.0.0", port=port)