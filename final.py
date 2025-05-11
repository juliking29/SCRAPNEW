import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import traceback
import re
from dateutil.parser import parse
import uvicorn

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
    
    try:
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        print(f"Error initializing ChromeDriver: {str(e)}")
        print(traceback.format_exc())
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
        date_part = date_str.split('-')[0].strip()  # Remove time part
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

# --- Scraper 1: La Liga Odds (from script.txt source 1-27) ---
def scrape_liga_odds():
    """Scraping function for La Liga odds page"""
    driver = init_driver()
    if not driver:
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
        
        time.sleep(3)
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
            
            bet_sections = combined_bet_section.find_all_next('p', string=lambda t: t and any(team in t for team in ['Girona', 'Atlético', 'Barcelona']))
            for bet in bet_sections[:3]:
                bet_text = safe_get_text(bet)
                strong_tag = bet.find_next('strong')
                odd_value = clean_odd_value(safe_get_text(strong_tag))
                parts = bet_text.split(':')
                match_part = parts[0].strip() if len(parts) > 0 else "N/A"
                bet_part = parts[1].strip() if len(parts) > 1 else "N/A"
                combined_bet["bets"].append({
                    "match": match_part,
                    "bet": bet_part,
                    "odd": odd_value
                })
            result["combined_bet"] = combined_bet
        
        match_table = soup.find('figure', class_='wp-block-table')
        if match_table:
            table = match_table.find('table')
            if table:
                rows = table.find_all('tr')[1:]
                for row in rows:
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
                                "odd": clean_odd_value(prediction_parts[-1].strip() if prediction_parts else "N/A")
                            }
                            result["matches"].append(match_data)
                    except Exception as e:
                        print(f"Error procesando fila de partido de La Liga: {str(e)}")
                        continue
        
        title_section = soup.find(lambda tag: tag.name and "Favoritos para ganar la liga española" in tag.get_text())
        if title_section:
            title_table = title_section.find_next('figure', class_='wp-block-table')
            if title_table:
                table = title_table.find('table')
                if table:
                    headers = [safe_get_text(th) for th in table.find('thead').find_all('th')] if table.find('thead') else []
                    rows = table.find_all('tr')[1:]
                    for row in rows:
                        cols = row.find_all('td')
                        if len(cols) == len(headers):
                            team_data = {"team": safe_get_text(cols[0])}
                            for i in range(1, min(len(headers), len(cols))):
                                team_data[headers[i]] = clean_odd_value(safe_get_text(cols[i]))
                            result["title_odds"].append(team_data)
            
    except Exception as e:
        print(f"Error durante el scraping de cuotas de La Liga: {str(e)}")
        print(traceback.format_exc())
        try:
            driver.save_screenshot("error_screenshot_liga.png")
            with open("error_page_source_liga.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("Cuotas La Liga: Archivos de depuración guardados")
        except:
            pass
        return {"error": str(e), "stack_trace": traceback.format_exc()}
    finally:
        if driver:
            driver.quit()
    
    return result

# --- Scraper 2: Relevo News (from script.txt source 28-53) ---
def scrape_relevo_news():
    """Scraping function for Relevo news page."""
    driver = init_driver()
    if not driver:
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
        
        time.sleep(5)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        articles_html = soup.select("div.grid--AB-C div.grid__col article.article")
        
        if not articles_html:
            print("Noticias Relevo: No se encontraron artículos. Revisa selectores o estructura de la página.")

        for article_tag in articles_html:
            try:
                title_tag = article_tag.find('h2', class_='article__title')
                title = "N/A"
                link = "N/A"
                if title_tag and title_tag.find('a'):
                    title_anchor = title_tag.find('a')
                    title = safe_get_text(title_anchor)
                    link = title_anchor.get('href', "N/A")
                    if link and not link.startswith('http'):
                        link = "https://www.relevo.com" + link

                authors_list = []
                author_section = article_tag.find('div', class_='author--art')
                if author_section:
                    author_signature = author_section.find('p', class_='author__signature')
                    if author_signature:
                        author_tags = author_signature.find_all('a')
                        for author_a in author_tags:
                            authors_list.append({
                                "name": safe_get_text(author_a),
                                "profile_url": author_a.get('href', "N/A")
                            })
                        if not authors_list and not author_tags :
                            authors_list.append({"name": safe_get_text(author_signature).split("Hace")[0].strip(), "profile_url": "N/A"})

                publication_date_str = "N/A"
                date_tag = None
                if author_section :
                    date_tag = author_section.find('time', class_='author__date')
                
                if date_tag:
                    if date_tag.has_attr('datetime'):
                        publication_date_str = date_tag['datetime']
                    else:
                        publication_date_str = safe_get_text(date_tag)
                publication_date = parse_relevo_date(publication_date_str)

                image_url = "N/A"
                img_container = article_tag.find('div', class_='article__container-img')
                if img_container:
                    img_tag = img_container.find('img')
                    if img_tag:
                        image_url = img_tag.get('src', "N/A")

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
                continue
            
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
        return {"error": str(e), "stack_trace": traceback.format_exc()}
    finally:
        if driver:
            driver.quit()
    
    return result

# --- Scraper 3: TablesLeague Data (from script.txt source 54-79) ---
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
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        content_div = soup.find('div', class_='content')
        if not content_div:
            result["error"] = "No se encontró el contenedor principal 'div.content'. La estructura del sitio puede haber cambiado."
            return result

        all_league_title_headers = []
        for header_candidate in content_div.find_all('div', class_='header'):
            if header_candidate.find('img', class_='flag'):
                all_league_title_headers.append(header_candidate)
        
        print(f"TablesLeague DEBUG: Encontradas {len(all_league_title_headers)} cabeceras de título de liga.")
        
        if not all_league_title_headers:
            result["error"] = "No se encontraron cabeceras de título de liga. No se pueden extraer tablas."
            return result
            
        for index, league_header_tag in enumerate(all_league_title_headers):
            league_data = {"name": "Unknown League", "teams": []}
            try:
                print(f"TablesLeague DEBUG: Procesando cabecera de liga #{index + 1}")
                
                league_name_text = "Unknown League"
                img_tag = league_header_tag.find('img', class_='flag')
                if img_tag and img_tag.next_sibling and isinstance(img_tag.next_sibling, str):
                    league_name_text = img_tag.next_sibling.strip()
                elif league_header_tag.contents:
                    for content_item in reversed(league_header_tag.contents):
                        if isinstance(content_item, str) and content_item.strip():
                            league_name_text = content_item.strip()
                            break
                    if league_name_text == "Unknown League" and league_header_tag.string is None:
                         league_name_text = league_header_tag.get_text(separator=" ", strip=True)
                    elif league_header_tag.string:
                        league_name_text = league_header_tag.string.strip()

                if not league_name_text or league_name_text == "Unknown League":
                    league_name_text = league_header_tag.get_text(separator=" ", strip=True).replace(img_tag.get('alt',''),'').strip() if img_tag else league_header_tag.get_text(separator=" ", strip=True)
                league_data["name"] = league_name_text
                print(f"TablesLeague DEBUG: Nombre de liga extraído: '{league_name_text}'")

                table_div = league_header_tag.find_next_sibling('div', class_='table')
                if not table_div:
                    print(f"TablesLeague WARN: No se encontró 'div.table' después de la cabecera para la liga: '{league_name_text}'. Saltando.")
                    continue
                
                rows = table_div.find_all('div', class_='row')
                if not rows:
                    print(f"TablesLeague WARN: No se encontraron filas (div.row) para la liga: '{league_name_text}'.")
                    continue

                column_headers = []
                header_row_tag = table_div.find('div', class_='row headers')
                if header_row_tag:
                    header_cells = header_row_tag.find_all('div', class_='cell')
                    column_headers = [cell.get_text(strip=True) for cell in header_cells]
                
                if not column_headers:
                    print(f"TablesLeague WARN: No se encontraron encabezados de columna para la liga: '{league_name_text}'. Usando predeterminados.")
                    column_headers = ["#", "Team", "M", "W", "D", "L", "G+", "G-", "GD", "PTS"]

                for row_tag in rows:
                    if 'headers' in row_tag.get('class', []):
                        continue 
                    
                    cells = row_tag.find_all('div', class_='cell')
                    team_stats = {}
                    for i, cell_tag in enumerate(cells):
                        header_name = column_headers[i] if i < len(column_headers) else f"column_{i+1}"
                        team_stats[header_name] = cell_tag.get_text(strip=True)
                    
                    if team_stats and "#" in team_stats and team_stats["#"]:
                         league_data["teams"].append(team_stats)
                
                if league_data["teams"]:
                    result["leagues"].append(league_data)
                else:
                    print(f"TablesLeague INFO: No se extrajeron equipos para la liga '{league_name_text}'. No se añadirá.")
            
            except Exception as e_league:
                print(f"TablesLeague ERROR al procesar la liga '{league_data.get('name', 'Desconocida')}' (índice {index}): {str(e_league)}")
                print(traceback.format_exc())
                continue 
    
    except requests.exceptions.RequestException as e_http:
        print(f"Error durante la petición HTTP a TablesLeague {url}: {str(e_http)}")
        result["error"] = f"Fallo en la petición HTTP: {str(e_http)}"
        result["stack_trace"] = traceback.format_exc()
    except Exception as e_general:
        print(f"Error general durante el scraping de TablesLeague: {str(e_general)}")
        result["error"] = f"Error inesperado durante el scraping de TablesLeague: {str(e_general)}"
        result["stack_trace"] = traceback.format_exc()
    
    if not result["leagues"] and "error" not in result:
        result["info"] = "El scraping de TablesLeague se completó, pero no se encontraron datos de ligas."

    return result

# --- Scraper 4: Transfermarkt General Odds (from script.txt source 80-101) ---
def scrape_transfermarkt_general_odds():
    """Main scraping function for Transfermarkt general odds"""
    driver = init_driver()
    if not driver:
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
                EC.presence_of_element_located((By.CLASS_NAME, "card__item-container"))
            )
            print("Cuotas Generales Transfermarkt: Contenido principal cargado")
        except Exception as e:
            print(f"Cuotas Generales Transfermarkt: Advertencia de carga de contenido: {str(e)}")
        
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        match_cards = soup.find_all('div', class_='card__item-container')
        print(f"Encontrados {len(match_cards)} tarjetas de partidos generales en Transfermarkt")
        
        if not match_cards:
            return {"error": "No se encontraron partidos generales en Transfermarkt. La estructura del sitio puede haber cambiado."}
        
        for card in match_cards:
            try:
                match_name_tag = card.find('div', class_='card__bonus-name')
                match_name = match_name_tag.text.strip() if match_name_tag else "Unknown Match"
                
                match_parts = match_name.split(' - ')
                if len(match_parts) >= 4:
                    league_teams = match_parts[0]
                    bet_type = ' - '.join(match_parts[1:-1])
                    odd_value = match_parts[-1]
                else:
                    league_teams = match_name
                    bet_type = "Unknown"
                    odd_value = "N/A"
                
                league = league_teams.split(':')[0].strip() if ':' in league_teams else "Unknown League"
                teams_part = league_teams.split(':')[1].strip() if ':' in league_teams else league_teams
                teams = [t.strip() for t in teams_part.split(' vs ')] if ' vs ' in teams_part else ["Unknown Team 1", "Unknown Team 2"]
                
                bookmaker_img = card.find('img')
                bookmaker_name = bookmaker_img['alt'] if bookmaker_img and 'alt' in bookmaker_img.attrs else "Unknown Bookmaker"
                bookmaker_logo = bookmaker_img['src'] if bookmaker_img and 'src' in bookmaker_img.attrs else "N/A"
                
                expiry_tag = card.find('div', class_='countdown')
                expiry_time = expiry_tag['data-valid-until'] if expiry_tag and 'data-valid-until' in expiry_tag.attrs else "N/A"
                
                cleaned_odd = clean_odd_value(odd_value)
                
                match_data = {
                    "league": league,
                    "homeTeam": teams[0] if len(teams) > 0 else "Unknown",
                    "awayTeam": teams[1] if len(teams) > 1 else "Unknown",
                    "betType": bet_type,
                    "odd": cleaned_odd,
                    "bookmaker": {
                        "name": bookmaker_name,
                        "logo": bookmaker_logo
                    },
                    "expiryTime": expiry_time,
                    "offerLink": card.find('a', class_='card__button')['href'] if card.find('a', class_='card__button') else "N/A"
                }
                result["matches"].append(match_data)
            except Exception as e:
                print(f"Error procesando tarjeta de partido general de Transfermarkt: {str(e)}")
                print(traceback.format_exc())
                continue
            
    except Exception as e:
        print(f"Error durante el scraping de cuotas generales de Transfermarkt: {str(e)}")
        print(traceback.format_exc())
        try:
            driver.save_screenshot("error_screenshot_transfermarkt_general.png")
            with open("error_page_source_transfermarkt_general.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("Cuotas Generales Transfermarkt: Archivos de depuración guardados")
        except:
            pass
        return {"error": str(e), "stack_trace": traceback.format_exc()}
    finally:
        if driver:
            driver.quit()
    
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
        if "error" in data:
             return JSONResponse(content=data, status_code=500)
        return JSONResponse(content=data)
    except Exception as e:
        print("ERROR API SCRAPER (/raspar-cuotas-liga):", e)
        print(traceback.format_exc())
        return JSONResponse(content={"error": str(e), "stack_trace": traceback.format_exc()}, status_code=500)

@app.get("/raspar-noticias-relevo")
def endpoint_raspar_noticias_relevo():
    try:
        data = scrape_relevo_news()
        if "error" in data:
             return JSONResponse(content=data, status_code=500)
        return JSONResponse(content=data)
    except Exception as e:
        print("ERROR API SCRAPER (/raspar-noticias-relevo):", e)
        print(traceback.format_exc())
        return JSONResponse(content={"error": str(e), "stack_trace": traceback.format_exc()}, status_code=500)

@app.get("/raspar-tablas-liga")
def endpoint_raspar_tablas_liga():
    try:
        data = scrape_tablesleague_data()
        if "error" in data and "stack_trace" not in data: 
            return JSONResponse(content=data, status_code=404 if "No se encontró" in data["error"] else 500)
        elif "error" in data:
            return JSONResponse(content=data, status_code=500)
        return JSONResponse(content=data)
    except Exception as e:
        print(f"ERROR en endpoint /raspar-tablas-liga: {str(e)}")
        print(traceback.format_exc())
        return JSONResponse(
            content={"error": "Error interno del servidor al procesar la solicitud.", "details": str(e)},
            status_code=500
        )

@app.get("/raspar-cuotas-generales-transfermarkt")
def endpoint_raspar_cuotas_generales_transfermarkt():
    try:
        data = scrape_transfermarkt_general_odds()
        if "error" in data:
             return JSONResponse(content=data, status_code=500)
        return JSONResponse(content=data)
    except Exception as e:
        print("ERROR API SCRAPER (/raspar-cuotas-generales-transfermarkt):", e)
        print(traceback.format_exc())
        return JSONResponse(content={"error": str(e), "stack_trace": traceback.format_exc()}, status_code=500)


if __name__ == "__main__":
    # Para ejecutar con FastAPI, usa: uvicorn nombre_del_archivo:app --reload
    # Ejemplo: uvicorn scraper_unificado:app --reload
    print("Intentando ejecutar el servidor Uvicorn...")
    uvicorn.run(app, host="0.0.0.0", port=8000)