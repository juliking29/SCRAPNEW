import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from fastapi import FastAPI, BackgroundTasks # <--- AÑADIDO para tareas en segundo plano
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import traceback
import re
from dateutil.parser import parse
import uvicorn
import os

app = FastAPI()

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Permite cualquier origen, considera restringirlo en producción
    allow_credentials=True,
    allow_methods=["*"], # Permite todos los métodos
    allow_headers=["*"], # Permite todas las cabeceras
)

# --- Helper Functions ---
def init_driver():
    """Initialize Chrome WebDriver in headless mode with improved error handling"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920x1080')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    # Optimización opcional: Deshabilitar imágenes si no son necesarias para el scraping
    # chrome_options.add_argument('--blink-settings=imagesEnabled=false')

    chrome_binary_path = os.environ.get("GOOGLE_CHROME_BIN")
    chromedriver_path = os.environ.get("CHROMEDRIVER_PATH")

    if chrome_binary_path:
        chrome_options.binary_location = chrome_binary_path
        print(f"Usando Chrome binary de: {chrome_binary_path}")
    else:
        print("ADVERTENCIA: GOOGLE_CHROME_BIN no está configurado. Selenium intentará usar la ubicación por defecto de Chrome.")

    try:
        if chromedriver_path:
            print(f"Usando ChromeDriver de: {chromedriver_path}")
            service = Service(executable_path=chromedriver_path)
            driver = webdriver.Chrome(service=service, options=chrome_options)
        else:
            print("ADVERTENCIA: CHROMEDRIVER_PATH no está configurado. Selenium intentará encontrar ChromeDriver en el PATH del sistema.")
            driver = webdriver.Chrome(options=chrome_options) # Requiere chromedriver en el PATH
        
        print("WebDriver inicializado correctamente.")
        return driver
    except Exception as e:
        print(f"Error FATAL al inicializar ChromeDriver: {str(e)}")
        print(traceback.format_exc())
        # Proveer más detalles sobre errores comunes de inicialización
        if "cannot find chrome binary" in str(e).lower():
            print("Detalle del error: No se encuentra el binario de Chrome. Verifica la variable GOOGLE_CHROME_BIN o la instalación de Chrome.")
        elif "executable needs to be in PATH" in str(e).lower():
            print("Detalle del error: ChromeDriver no se encuentra en el PATH. Verifica la variable CHROMEDRIVER_PATH o la ubicación de chromedriver.")
        elif "session not created" in str(e).lower():
            print("Detalle del error: No se pudo crear la sesión. Puede ser por incompatibilidad de versiones Chrome/ChromeDriver o problemas de recursos.")
        return None

def clean_odd_value(odd_text):
    if not odd_text:
        return "N/A"
    odd_text = odd_text.strip().replace('\xa0', ' ').replace('\u00a0', ' ')
    match = re.search(r'(\d+\.?\d*)', odd_text)
    return match.group(1) if match else odd_text

def parse_match_date_liga(date_str):
    if not date_str:
        return "N/A"
    try:
        date_part = date_str.split('-')[0].strip()
        return parse(date_part, dayfirst=True).strftime('%Y-%m-%d %H:%M')
    except Exception as e:
        print(f"Error parsing date (liga): {date_str} - {str(e)}")
        return date_str

def parse_match_date_transfermarkt_general(date_str):
    try:
        return parse(date_str).strftime('%Y-%m-%d %H:%M')
    except Exception as e:
        print(f"Error parsing date (transfermarkt general): {date_str} - {str(e)}")
        return date_str

def safe_get_text(element, default="N/A"):
    if element is None:
        return default
    try:
        return element.get_text(strip=True)
    except:
        return default

def parse_relevo_date(date_str):
    if not date_str:
        return "N/A"
    try:
        return parse(date_str).strftime('%Y-%m-%d %H:%M:%S')
    except Exception as e:
        print(f"Error parsing date (relevo): {date_str} - {str(e)}")
        return date_str

# --- Scraper 1: La Liga Odds ---
def scrape_liga_odds():
    print("Iniciando scrape_liga_odds...")
    driver = init_driver()
    if not driver:
        return {"error": "Failed to initialize browser", "details": "WebDriver could not start. Check logs for init_driver errors."}
    
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
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, "oddscomp-widget-iframe-container"))
        )
        print("Cuotas La Liga: Contenido principal cargado")
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        combined_bet_section = soup.find('h2', string='Apuesta combinada de la jornada')
        if combined_bet_section:
            combined_bet_data = {"description": "", "bets": []}
            desc_paragraphs = []
            next_elem = combined_bet_section.find_next_sibling('p')
            while next_elem and next_elem.name == 'p':
                desc_paragraphs.append(safe_get_text(next_elem))
                next_elem = next_elem.find_next_sibling()
            combined_bet_data["description"] = " ".join(desc_paragraphs)
            
            bet_container = combined_bet_section.find_parent()
            if bet_container:
                potential_bets_p = bet_container.find_all('p')
                parsed_bets_count = 0
                for p_tag in potential_bets_p:
                    if parsed_bets_count >= 3: break
                    p_text = safe_get_text(p_tag)
                    if ':' in p_text and any(kw in p_text for kw in ['Girona', 'Atlético', 'Barcelona', 'Real Madrid', 'vs']):
                        strong_tag = p_tag.find('strong') or p_tag.find_next('strong')
                        odd_value = clean_odd_value(safe_get_text(strong_tag)) if strong_tag else "N/A"
                        parts = p_text.split(':', 1)
                        match_part = parts[0].strip()
                        bet_part = parts[1].split(odd_value)[0].strip() if len(parts) > 1 and odd_value != "N/A" else (parts[1].strip() if len(parts) > 1 else "N/A")
                        combined_bet_data["bets"].append({"match": match_part, "bet": bet_part, "odd": odd_value})
                        parsed_bets_count += 1
            result["combined_bet"] = combined_bet_data
        else:
            print("Cuotas La Liga: Sección 'Apuesta combinada de la jornada' no encontrada.")

        match_table_figure = soup.find('figure', class_='wp-block-table')
        if match_table_figure and (table := match_table_figure.find('table')):
            for row in table.find_all('tr')[1:]:
                try:
                    cols = row.find_all('td')
                    if len(cols) >= 4:
                        prediction_text = safe_get_text(cols[3])
                        prediction_parts = prediction_text.split('➡')
                        match_data = {
                            "teams": safe_get_text(cols[0]),
                            "date": parse_match_date_liga(safe_get_text(cols[1])),
                            "stadium": safe_get_text(cols[2]),
                            "prediction": prediction_parts[0].strip() if prediction_parts else "N/A",
                            "odd": clean_odd_value(prediction_parts[-1].strip()) if len(prediction_parts) > 1 else "N/A"
                        }
                        result["matches"].append(match_data)
                except Exception as e_row:
                    print(f"Error procesando fila de partido La Liga: {e_row}")
        else:
            print("Cuotas La Liga: Tabla de partidos no encontrada.")
            
        title_section = soup.find(lambda tag: tag.name and "Favoritos para ganar la liga española" in tag.get_text())
        if title_section and (title_table_figure := title_section.find_next('figure', class_='wp-block-table')) and \
           (table := title_table_figure.find('table')):
            headers = [safe_get_text(th) for th in table.find('thead').find_all('th')] if table.find('thead') else []
            tbody_rows = table.find('tbody').find_all('tr') if table.find('tbody') else table.find_all('tr')[1:]
            for row in tbody_rows:
                cols = row.find_all('td')
                if cols:
                    team_data = {"team": safe_get_text(cols[0])}
                    for i, header in enumerate(headers[1:], 1): # Start from second header
                        if i < len(cols):
                            team_data[header] = clean_odd_value(safe_get_text(cols[i]))
                        else: # Fallback if less cols than headers
                            team_data[header] = "N/A"
                    if not headers and len(cols) > 1: # No headers, generic bookmaker names
                         for i in range(1, len(cols)):
                            team_data[f"Bookmaker_{i}"] = clean_odd_value(safe_get_text(cols[i]))
                    result["title_odds"].append(team_data)
        else:
            print("Cuotas La Liga: Sección/tabla de favoritos para ganar la liga no encontrada.")
            
    except Exception as e:
        print(f"Error durante el scraping de cuotas de La Liga: {str(e)}")
        print(traceback.format_exc())
        result["error_scraping"] = f"Error during scraping process: {str(e)}"
    finally:
        if driver:
            driver.quit()
            print("Cuotas La Liga: WebDriver cerrado.")
    print(f"scrape_liga_odds finalizado. Partidos: {len(result.get('matches',[]))}, Cuotas Título: {len(result.get('title_odds',[]))}")
    return result

# --- Scraper 2: Relevo News ---
def scrape_relevo_news():
    print("Iniciando scrape_relevo_news...")
    driver = init_driver()
    if not driver:
        return {"error": "Failed to initialize browser", "details": "WebDriver could not start."}
    
    url = "https://www.relevo.com/futbol/mercado-fichajes/"
    print(f"Accediendo a Noticias Relevo: {url}")
    result = {"scraped_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "articles": []}
    
    try:
        driver.get(url)
        WebDriverWait(driver, 25).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.grid--AB-C article.article"))
        )
        print("Noticias Relevo: Contenido principal cargado")
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        articles_html = soup.select("div.grid--AB-C div.grid__col article.article")
        
        if not articles_html:
            print("Noticias Relevo: No se encontraron artículos.")
            result["info"] = "No articles found on Relevo at this time."
            return result

        for article_tag in articles_html:
            try:
                title, link = "N/A", "N/A"
                if (title_anchor := (article_tag.find('h2', class_='article__title') or article_tag.find('h3', class_='article__title')) \
                                  and (article_tag.find('h2', class_='article__title') or article_tag.find('h3', class_='article__title')).find('a')):
                    title = safe_get_text(title_anchor)
                    link_href = title_anchor.get('href', "N/A")
                    link = "https://www.relevo.com" + link_href if link_href and not link_href.startswith('http') else link_href

                authors_list = []
                if (author_section := article_tag.find('div', class_='author--art')):
                    if (author_signature := author_section.find('p', class_='author__signature')):
                        author_tags_a = author_signature.find_all('a')
                        if author_tags_a:
                            for author_a in author_tags_a:
                                name = safe_get_text(author_a)
                                url_ = author_a.get('href', "N/A")
                                profile_url = "https://www.relevo.com" + url_ if url_ and not url_.startswith('http') else url_
                                authors_list.append({"name": name, "profile_url": profile_url})
                        else: # No <a> tags, try to get text
                            author_name_candidate = safe_get_text(author_signature).split("Hace")[0].strip()
                            if author_name_candidate: authors_list.append({"name": author_name_candidate, "profile_url": "N/A"})
                    if not authors_list: # Fallback: find any author links in section
                        for author_link_tag in author_section.find_all('a', href=re.compile(r'/autor/')):
                            name = safe_get_text(author_link_tag)
                            url_ = author_link_tag.get('href')
                            profile_url = "https://www.relevo.com" + url_ if url_ and not url_.startswith('http') else url_
                            authors_list.append({"name": name, "profile_url": profile_url})
                
                publication_date_str = "N/A"
                date_tag = article_tag.find('time', class_='author__date') or article_tag.find('time')
                if date_tag:
                    publication_date_str = date_tag.get('datetime', safe_get_text(date_tag))
                publication_date = parse_relevo_date(publication_date_str)

                image_url = "N/A"
                if (img_container := article_tag.find('div', class_='article__container-img')) and \
                   (img_tag := img_container.find('img')):
                    image_url = img_tag.get('src', img_tag.get('data-src', "N/A"))

                result["articles"].append({
                    "title": title, "link": link,
                    "authors": authors_list if authors_list else [{"name": "N/A", "profile_url": "N/A"}],
                    "publication_date_iso": publication_date if publication_date != "N/A" else publication_date_str,
                    "image_url": image_url
                })
            except Exception as e_article:
                print(f"Error procesando artículo de Relevo: {e_article}")
    except Exception as e:
        print(f"Error durante el scraping de Relevo: {str(e)}")
        print(traceback.format_exc())
        result["error_scraping"] = f"Error during Relevo scraping: {str(e)}"
    finally:
        if driver:
            driver.quit()
            print("Noticias Relevo: WebDriver cerrado.")
    print(f"scrape_relevo_news finalizado. Artículos: {len(result.get('articles',[]))}")
    return result

# --- Scraper 3: TablesLeague Data ---
def scrape_tablesleague_data():
    url = "https://m.tablesleague.com/"
    print(f"Accediendo a TablesLeague: {url}")
    result = {"scraped_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "leagues": []}
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        if not (content_div := soup.find('div', class_='content')):
            result["error"] = "No se encontró 'div.content' en TablesLeague."
            return result

        league_headers = [h for h in content_div.find_all('div', class_='header') if h.find('img', class_='flag')]
        if not league_headers:
            result["info"] = "No se encontraron cabeceras de liga con banderas en TablesLeague."
            return result

        for league_header_tag in league_headers:
            league_name = "Unknown League"
            if (img_tag := league_header_tag.find('img', class_='flag')) and \
               img_tag.next_sibling and isinstance(img_tag.next_sibling, str):
                league_name = img_tag.next_sibling.strip()
            elif (a_tag := league_header_tag.find('a')):
                league_name = safe_get_text(a_tag)
            else: # Fallback
                full_header_text = league_header_tag.get_text(separator=" ", strip=True)
                img_alt = img_tag.get('alt', '') if img_tag else ''
                league_name = full_header_text.replace(img_alt, '').strip() or "League Name Not Found"
            
            league_data = {"name": league_name, "teams": []}
            if not (table_div := league_header_tag.find_next_sibling('div', class_='table')):
                print(f"TablesLeague WARN: No 'div.table' para liga '{league_name}'.")
                continue
            
            rows = table_div.find_all('div', class_='row')
            if len(rows) <= 1: # Need more than just a header row potentially
                print(f"TablesLeague WARN: No filas de datos para liga '{league_name}'.")
                continue

            column_map = {
                "#": "Position", "POS": "Position", "TEAM": "Team", "CLUB": "Team",
                "M": "Played", "P": "Played", "PJ": "Played", "PLD": "Played",
                "W": "Won", "G": "Won", "PG": "Won", "D": "Drawn", "E": "Drawn", "PE": "Drawn",
                "L": "Lost", "PP": "Lost", # 'P' is ambiguous, might conflict if also for Points
                "G+": "GoalsFor", "GF": "GoalsFor", "F": "GoalsFor",
                "G-": "GoalsAgainst", "GA": "GoalsAgainst", "A": "GoalsAgainst",
                "GD": "GoalDifference", "DG": "GoalDifference", "DIF": "GoalDifference",
                "PTS": "Points", "PUNTOS": "Points"
            }
            column_headers_tags = table_div.find('div', class_='row headers')
            final_headers = [column_map.get(safe_get_text(cell).upper(), safe_get_text(cell)) 
                             for cell in column_headers_tags.find_all('div', class_='cell')] if column_headers_tags else []

            for row_tag in rows:
                if 'headers' in row_tag.get('class', []): continue
                cells = row_tag.find_all('div', class_='cell')
                if not cells: continue
                
                team_stats = {}
                for i, cell_tag in enumerate(cells):
                    header_name = final_headers[i] if i < len(final_headers) and final_headers[i] else f"column_{i+1}"
                    team_stats[header_name] = safe_get_text(cell_tag)
                
                if team_stats.get("Team"):
                    league_data["teams"].append(team_stats)
            
            if league_data["teams"]: result["leagues"].append(league_data)
        
    except requests.exceptions.RequestException as e_http:
        result["error"] = f"Fallo HTTP en TablesLeague: {e_http}"
    except Exception as e_general:
        result["error"] = f"Error inesperado en TablesLeague: {e_general}"
        print(traceback.format_exc())
    
    if not result["leagues"] and "error" not in result and "info" not in result:
        result["info"] = "Scraping de TablesLeague completado, no se encontraron datos de ligas procesables."
    print(f"scrape_tablesleague_data finalizado. Ligas: {len(result.get('leagues', []))}")
    return result

# --- Scraper 4: Transfermarkt General Odds ---
def scrape_transfermarkt_general_odds():
    print("Iniciando scrape_transfermarkt_general_odds...")
    driver = init_driver()
    if not driver:
        return {"error": "Failed to initialize browser", "details": "WebDriver could not start."}
    
    url = "https://www.transfermarkt.es/apuestas/cuotas/"
    print(f"Accediendo a Cuotas Generales Transfermarkt: {url}")
    result = {"scraped_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "matches": []}
    
    try:
        driver.get(url)
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CLASS_NAME, "card__item-container"))
        )
        print("Cuotas Generales Transfermarkt: Contenido cargado")
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        match_cards = soup.find_all('div', class_='card__item-container')
        
        if not match_cards:
            result["info"] = "No se encontraron tarjetas de partidos generales en Transfermarkt."
            return result

        for card in match_cards:
            try:
                match_name = safe_get_text(card.find('div', class_='card__bonus-name'), "Unknown Match")
                league, home_team, away_team, bet_type, odd_value = "N/A", "N/A", "N/A", "N/A", "N/A"

                parts = match_name.split(' - ')
                if len(parts) >= 2:
                    odd_value = parts[-1]
                    main_info = ' - '.join(parts[:-1])
                    bet_type_parts = main_info.rsplit(' - ', 1) # rsplit to get bet_type if present
                    if len(bet_type_parts) > 1 and len(bet_type_parts[-1]) < 50: # Heuristic
                        bet_type = bet_type_parts[-1].strip()
                        match_info_str = bet_type_parts[0].strip()
                    else:
                        bet_type = "Resultado del partido" # Default
                        match_info_str = main_info.strip()

                    league_teams_parts = match_info_str.split(':', 1)
                    if len(league_teams_parts) > 1:
                        league = league_teams_parts[0].strip()
                        teams_str = league_teams_parts[1].strip()
                    else:
                        league = "General" # Default if no league prefix
                        teams_str = match_info_str.strip()
                    
                    teams = [t.strip() for t in teams_str.split('vs')]
                    if len(teams) == 2: home_team, away_team = teams[0], teams[1]
                    elif len(teams) == 1: home_team = teams[0]
                else: # Fallback if parsing ' - ' fails
                    if (num_match := re.search(r'(\d+\.\d+)$', match_name)):
                        odd_value = num_match.group(1)
                    # Could add more robust parsing here if needed
                    bet_type = match_name # Use full name as bet_type if cannot parse

                bookmaker_name, bookmaker_logo = "N/A", "N/A"
                if (bookmaker_img := card.find('img', class_='card__logo')):
                    bookmaker_name = bookmaker_img.get('alt', safe_get_text(bookmaker_img)).strip()
                    bookmaker_logo = bookmaker_img.get('src', "N/A")

                expiry_time_str = "N/A"
                if (expiry_tag := card.find('div', class_='countdown')) and expiry_tag.has_attr('data-valid-until'):
                     expiry_time_str = expiry_tag['data-valid-until']
                
                offer_link = "N/A"
                if (offer_link_tag := card.find('a', class_='card__button')) and offer_link_tag.has_attr('href'):
                    offer_link = offer_link_tag['href']
                    if offer_link.startswith('/'): offer_link = "https://www.transfermarkt.es" + offer_link

                result["matches"].append({
                    "league": league, "homeTeam": home_team, "awayTeam": away_team,
                    "betType": bet_type, "odd": clean_odd_value(odd_value),
                    "bookmaker": {"name": bookmaker_name, "logo": bookmaker_logo},
                    "expiryTime": expiry_time_str, "offerLink": offer_link
                })
            except Exception as e_card:
                print(f"Error procesando tarjeta general Transfermarkt: {e_card}")
    except Exception as e:
        print(f"Error en scraping general Transfermarkt: {str(e)}")
        print(traceback.format_exc())
        result["error_scraping"] = f"Error during general Transfermarkt scraping: {str(e)}"
    finally:
        if driver:
            driver.quit()
            print("Cuotas Generales Transfermarkt: WebDriver cerrado.")
    print(f"scrape_transfermarkt_general_odds finalizado. Partidos: {len(result.get('matches',[]))}")
    return result

# --- API Endpoints ---

# ----- Gestión de Tareas en Segundo Plano (Conceptual - MUY RECOMENDADO PARA PRODUCCIÓN) -----
# tasks_db = {} 
# def run_scrape_in_background(task_id: str, scrape_function, *args):
#     try:
#         print(f"Background task {task_id} ({scrape_function.__name__}) started.")
#         data = scrape_function(*args)
#         tasks_db[task_id] = {"status": "completed", "data": data, "timestamp": datetime.now().isoformat()}
#         print(f"Background task {task_id} completed.")
#     except Exception as e:
#         print(f"Background task {task_id} failed: {str(e)}")
#         tasks_db[task_id] = {"status": "failed", "error": str(e), "trace": traceback.format_exc(), "timestamp": datetime.now().isoformat()}

# @app.post("/v2/start-scraping-task/{scraper_name}")
# async def start_background_task_v2(scraper_name: str, background_tasks: BackgroundTasks):
#     task_id = f"{scraper_name}_{int(datetime.now().timestamp())}"
#     tasks_db[task_id] = {"status": "pending", "task_id": task_id, "scraper_name": scraper_name, "started_at": datetime.now().isoformat()}
#     scrape_func_map = {
#         "liga_odds": scrape_liga_odds, "relevo_news": scrape_relevo_news, 
#         "transfermarkt_general": scrape_transfermarkt_general_odds, "tables_liga": scrape_tablesleague_data
#     }
#     if scraper_name not in scrape_func_map:
#         return JSONResponse(content={"error": "Invalid scraper name"}, status_code=400)
#     background_tasks.add_task(run_scrape_in_background, task_id, scrape_func_map[scraper_name])
#     return JSONResponse(content=tasks_db[task_id], status_code=202)

# @app.get("/v2/scraping-task-status/{task_id}")
# async def get_task_status_v2(task_id: str):
#     task = tasks_db.get(task_id)
#     if not task:
#         return JSONResponse(content={"error": "Task not found"}, status_code=404)
#     # Si la tarea se completó, podrías decidir devolver el status_code original del scraper si tuvo error
#     if task.get("status") == "completed" and task.get("data", {}).get("error"):
#         if task["data"]["error"] == "Failed to initialize browser":
#             return JSONResponse(content=task, status_code=503)
#         return JSONResponse(content=task, status_code=500) # O 200 con el error dentro de "data"
#     return JSONResponse(content=task)
# ----- Endpoints Síncronos Actuales (Propensos a Timeouts para Scrapers con Selenium) -----

@app.get("/")
def root():
    return {
        "message": "Bienvenido a la API Unificada de Scrapers",
        "rutas_sincronas_disponibles": [
            "/raspar-cuotas-liga", "/raspar-noticias-relevo",
            "/raspar-tablas-liga", "/raspar-cuotas-generales-transfermarkt"
        ],
        "rutas_asincronas_recomendadas (ver comentarios en código)": [
            "POST /v2/start-scraping-task/{scraper_name}",
            "GET /v2/scraping-task-status/{task_id}"
        ],
        "available_scraper_names_for_start_task": ["liga_odds", "relevo_news", "tables_liga", "transfermarkt_general"]
    }

def handle_scraper_response(data, endpoint_name: str):
    print(f"Respuesta de {endpoint_name}: {json.dumps(data, indent=2, ensure_ascii=False, default=str)}")
    if "error" in data and data["error"] == "Failed to initialize browser":
        return JSONResponse(content=data, status_code=503)
    if "error_scraping" in data:
        return JSONResponse(content=data, status_code=500)
    if "error" in data: # Otros errores genéricos del scraper
        return JSONResponse(content=data, status_code=500) 
    # Si hay 'info' y no hay datos clave, es un 200 con info
    if "info" in data and not any(k in data for k in ["matches", "articles", "leagues"]):
        return JSONResponse(content=data, status_code=200)
    return JSONResponse(content=data)

@app.get("/raspar-cuotas-liga")
def endpoint_raspar_cuotas_liga():
    print("Endpoint /raspar-cuotas-liga (síncrono) llamado.")
    try:
        data = scrape_liga_odds()
        return handle_scraper_response(data, "scrape_liga_odds")
    except Exception as e:
        print(f"ERROR CRÍTICO API (/raspar-cuotas-liga): {e}\n{traceback.format_exc()}")
        return JSONResponse(content={"error": "Error interno del servidor", "details": str(e)}, status_code=500)

@app.get("/raspar-noticias-relevo")
def endpoint_raspar_noticias_relevo():
    print("Endpoint /raspar-noticias-relevo (síncrono) llamado.")
    try:
        data = scrape_relevo_news()
        return handle_scraper_response(data, "scrape_relevo_news")
    except Exception as e:
        print(f"ERROR CRÍTICO API (/raspar-noticias-relevo): {e}\n{traceback.format_exc()}")
        return JSONResponse(content={"error": "Error interno del servidor", "details": str(e)}, status_code=500)

@app.get("/raspar-tablas-liga") 
def endpoint_raspar_tablas_liga():
    print("Endpoint /raspar-tablas-liga (síncrono) llamado.")
    try:
        data = scrape_tablesleague_data()
        # Este scraper no usa Selenium, así que el manejo de 'Failed to initialize browser' no aplica directamente.
        if "error" in data: # Errores específicos de este scraper (HTTP, parsing)
            status_code = 500
            if "No se encontró el contenedor principal" in data["error"] or "No se encontraron cabeceras de título" in data["error"]:
                status_code = 404 # O 503 si el sitio fuente está mal
            elif "Fallo en la petición HTTP" in data["error"]:
                status_code = 502 # Bad Gateway
            return JSONResponse(content=data, status_code=status_code)
        if "info" in data and not data.get("leagues"):
            return JSONResponse(content=data, status_code=200) # OK, pero sin datos de ligas
        return JSONResponse(content=data)
    except Exception as e:
        print(f"ERROR CRÍTICO API (/raspar-tablas-liga): {e}\n{traceback.format_exc()}")
        return JSONResponse(content={"error": "Error interno del servidor", "details": str(e)}, status_code=500)

@app.get("/raspar-cuotas-generales-transfermarkt")
def endpoint_raspar_cuotas_generales_transfermarkt():
    print("Endpoint /raspar-cuotas-generales-transfermarkt (síncrono) llamado.")
    try:
        data = scrape_transfermarkt_general_odds()
        return handle_scraper_response(data, "scrape_transfermarkt_general_odds")
    except Exception as e:
        print(f"ERROR CRÍTICO API (/raspar-cuotas-generales-transfermarkt): {e}\n{traceback.format_exc()}")
        return JSONResponse(content={"error": "Error interno del servidor", "details": str(e)}, status_code=500)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host_to_bind = os.environ.get("HOST", "0.0.0.0") # Para Railway y contenedores
    reload_status = os.environ.get("UVICORN_RELOAD", "true").lower() == "true" # Controlar reload
    
    print(f"Intentando ejecutar Uvicorn en host {host_to_bind}, puerto {port}. Reload: {reload_status}")
    uvicorn.run("final:app", host=host_to_bind, port=port, reload=reload_status)