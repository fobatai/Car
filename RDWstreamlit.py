import streamlit as st
import requests
import pandas as pd
import json
import os
from typing import Dict, Any
from bs4 import BeautifulSoup


#########################################
# Functies voor persistente opslag
#########################################

DATA_FILE = "data.json"

def load_persistent_data():
    """Laad data uit een lokaal JSON-bestand en zet deze in de session_state."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
        st.session_state.overrides = data.get("overrides", {})
        st.session_state.cars_info = data.get("cars_info", {})
        st.session_state.rdw_cache = data.get("rdw_cache", {})
        st.session_state.wegenbelasting_cache = data.get("wegenbelasting_cache", {})
        st.session_state.stamdata = data.get("stamdata", {})
    else:
        st.session_state.overrides = {}
        st.session_state.cars_info = {}
        st.session_state.rdw_cache = {}
        st.session_state.wegenbelasting_cache = {}
        st.session_state.stamdata = {}

def save_persistent_data():
    """Sla de data uit de session_state veilig op in een JSON-bestand."""
    data = {
        "overrides": st.session_state.overrides,
        "cars_info": st.session_state.cars_info,
        "rdw_cache": st.session_state.rdw_cache,
        "wegenbelasting_cache": st.session_state.wegenbelasting_cache,
        "stamdata": st.session_state.stamdata,
    }
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

#########################################
# Eenvoudige authenticatie
#########################################
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("Login")
    password = st.text_input("Voer wachtwoord in", type="password")
    if st.button("Login"):
        if password == "AutoPonti":
            st.session_state.authenticated = True
            load_persistent_data()  # laad eerdere data
            st.success("Succesvol ingelogd!")
            st.rerun()
        else:
            st.error("Onjuist wachtwoord")
    st.stop()

#########################################
# Python-functies (geoptimaliseerd)
#########################################

def get_all_rdw_data(kenteken: str) -> Dict[str, Any]:
    """Haal ALLE RDW-gegevens voor een kenteken op in één keer (gecached)."""
    kenteken = kenteken.upper().replace("-", "").strip()
    if kenteken in st.session_state.rdw_cache:
        return st.session_state.rdw_cache[kenteken]
    try:
        url_basis = f"https://opendata.rdw.nl/resource/m9d7-ebf2.json?kenteken={kenteken}"
        response_basis = requests.get(url_basis)
        response_basis.raise_for_status()
        data_basis = response_basis.json()
        if not data_basis:
            st.session_state.rdw_cache[kenteken] = {"error": "Geen data gevonden"}
            return {"error": "Geen data gevonden"}
        data_basis = data_basis[0]
        url_brandstof = f"https://opendata.rdw.nl/resource/8ys7-d773.json?kenteken={kenteken}"
        response_brandstof = requests.get(url_brandstof)
        response_brandstof.raise_for_status()
        data_brandstof = response_brandstof.json()
        if data_brandstof:
            data_basis.update(data_brandstof[0])
        for date_field in ["datum_eerste_toelating", "vervaldatum_apk"]:
            if data_basis.get(date_field):
                try:
                    data_basis[date_field] = pd.to_datetime(data_basis[date_field], dayfirst=True).strftime('%d-%m-%Y')
                except ValueError:
                    pass
        if data_basis.get("datum_eerste_toelating"):
            try:
                data_basis["datum_eerste_toelating"] = str(pd.to_datetime(data_basis["datum_eerste_toelating"], dayfirst=True).year)
            except ValueError:
                pass
        st.session_state.rdw_cache[kenteken] = data_basis
        return data_basis
    except requests.RequestException as e:
        st.session_state.rdw_cache[kenteken] = {"error": f"Error: {e}"}
        return {"error": f"Error: {e}"}

def get_rdw_data(kenteken: str, veld: str) -> Any:
    """Haal een specifiek RDW-veld op, gebruikmakend van de gecachede data."""
    all_data = get_all_rdw_data(kenteken)
    if "error" in all_data:
        return all_data["error"]
    return all_data.get(veld)

def get_rdw_brandstof(kenteken: str) -> str:
    """Haal brandstoftype op."""
    return get_rdw_data(kenteken, "brandstof_omschrijving")

def get_rdw_brandstof_verbruik(kenteken: str, brandstof_type_keuze: str = None) -> float:
    """
    Haal brandstofverbruik op, met WLTP-voorkeur en correctie/fallback voor elektrische auto's.
    
    Voor elektrische auto's:
      - Haal de waarde op uit 'elektrisch_verbruik_enkel_elektrisch_wltp'.
      - Als de waarde ontbreekt, gebruik een fallback van 170 (wat resulteert in 17 kWh/100km).
      - Deel de waarde door 10 zodat bijvoorbeeld 157 resulteert in 15.7 kWh/100km.
    """
    brandstof = get_rdw_brandstof(kenteken)
    if brandstof_type_keuze == "ELEKTRICITEIT" or (brandstof and "ELEKTR" in brandstof.upper()):
        verbruik = get_rdw_data(kenteken, "elektrisch_verbruik_enkel_elektrisch_wltp")
        if verbruik is None or verbruik == "Veld niet gevonden":
            verbruik = 170
        try:
            numeric_verbruik = float(verbruik)
        except (ValueError, TypeError):
            numeric_verbruik = 0.0
        return numeric_verbruik / 10
    else:
        verbruik = get_rdw_data(kenteken, "brandstof_verbruik_gecombineerd_wltp")
        if verbruik is None or verbruik == "Veld niet gevonden":
            verbruik = get_rdw_data(kenteken, "brandstofverbruik_gecombineerd")
        try:
            numeric_verbruik = float(verbruik)
        except (ValueError, TypeError):
            numeric_verbruik = 0.0
        return numeric_verbruik

def get_overijssel_price(kenteken: str) -> str:
    """Haal wegenbelasting op van wegenbelasting.net (webscraping, gecached)."""
    if kenteken in st.session_state.wegenbelasting_cache:
        return st.session_state.wegenbelasting_cache[kenteken]
    url = "https://www.wegenbelasting.net/kenteken-check/"
    post_data = {"submit_berekenen_kenteken": "1", "k": kenteken}
    try:
        response = requests.post(url, data=post_data)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find("table", class_="wb-resultaat")
        if table:
            for row in table.find_all("tr"):
                if "Overijssel" in row.text:
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        price_overijssel = cells[1].text.strip()
                        st.session_state.wegenbelasting_cache[kenteken] = price_overijssel
                        return price_overijssel
        st.session_state.wegenbelasting_cache[kenteken] = "Niet gevonden"
        return "Niet gevonden"
    except requests.RequestException as e:
        st.session_state.wegenbelasting_cache[kenteken] = f"Error: {e}"
        return f"Error: {e}"

#########################################
# Applicatie-instellingen en interface
#########################################

st.set_page_config(layout="wide")
st.title("🚗 Autokosten Calculator")
st.write("""
Deze applicatie berekent de kosten van auto's.
Voer hieronder één of meerdere kentekens in (één per regel).
""")

# --- Stamdata (Globaal) ---
st.sidebar.header("Stamdata (Globaal)")
jaarlijkse_km = st.sidebar.number_input("Jaarlijkse kilometers", value=st.session_state.stamdata.get('jaarlijkse_km', 35000), min_value=0, key="jaarlijkse_km_global")
brandstofprijs = st.sidebar.number_input("Brandstofprijs (€/L)", value=st.session_state.stamdata.get('brandstofprijs', 2.00), min_value=0.0, key="brandstofprijs_global")
elektraprijs = st.sidebar.number_input("Elektriciteitsprijs (€/kWh)", value=st.session_state.stamdata.get('elektraprijs', 0.35), min_value=0.0, key="elektraprijs_global")
rente = st.sidebar.number_input("Rente (%)", value=st.session_state.stamdata.get('rente', 5.0), min_value=0.0, max_value=100.0, key="rente_global")
st.session_state.stamdata['jaarlijkse_km'] = jaarlijkse_km
st.session_state.stamdata['brandstofprijs'] = brandstofprijs
st.session_state.stamdata['elektraprijs'] = elektraprijs
st.session_state.stamdata['rente'] = rente

# Invoer van kentekens
kentekens = st.text_area("Voer kentekens in (één per regel):", height=100)
if kentekens:
    kenteken_list = [k.strip().upper() for k in kentekens.split('\n') if k.strip()]
    
    # Lijst voor resultaten
    results = []
    
    # Verwerk per auto de data en berekeningen
    for kenteken in kenteken_list:
        car_data = get_all_rdw_data(kenteken)
        if "error" in car_data:
            continue
        
        catalogusprijs = car_data.get("catalogusprijs")
        merk = car_data.get("merk", "Onbekend")
        model = car_data.get("handelsbenaming", "Onbekend")
        
        # Overrides en standaardwaarden
        aanschafwaarde = st.session_state.overrides.get(
            f'aanschaf_{kenteken}', 
            float(catalogusprijs) if catalogusprijs and catalogusprijs != "Geen data gevonden" else 15000.00
        )
        afschrijving_percentage = st.session_state.overrides.get(f'afschrijving_{kenteken}', 12.0)
        # Verzekering per maand: standaard 200 €
        verzekering_per_maand = st.session_state.overrides.get(f'verzekering_{kenteken}', 200.0)
        # Leaseprijs (maandelijks): standaard 0 €
        leaseprijs = st.session_state.overrides.get(f'lease_{kenteken}', 0.0)
        
        bouwjaar = car_data.get("datum_eerste_toelating")
        gewicht = car_data.get("massa_rijklaar")
        kleur = car_data.get("eerste_kleur")
        apk = car_data.get("vervaldatum_apk")
        brandstof = car_data.get("brandstof_omschrijving")
        co2 = car_data.get("co2_uitstoot_gecombineerd")
        if co2 is None or co2 == "Veld niet gevonden":
            co2 = car_data.get("co2_uitstoot_nettomax")
        fijnstof = car_data.get("uitstoot_deeltjes_licht")
        toelating = car_data.get("datum_eerste_toelating")
        
        # Rijtuigenbelasting: probeer de waarde als numeriek te verkrijgen
        wb_str = get_overijssel_price(kenteken)
        try:
            if wb_str.startswith("€"):
                wb_numeric = float(wb_str.split(" ")[1].replace(",", "."))
            else:
                wb_numeric = float(wb_str.replace(",", "."))
        except Exception:
            wb_numeric = 0.0
        
        # Berekeningen
        afschrijving_per_maand_calc = (aanschafwaarde * (afschrijving_percentage / 100)) / 12
        verbruik = get_rdw_brandstof_verbruik(kenteken)
        if brandstof and "ELEKTR" in brandstof.upper():
            kosten_brandstof_per_jaar = (jaarlijkse_km / 100) * verbruik * elektraprijs
        else:
            kosten_brandstof_per_jaar = (jaarlijkse_km / 100) * verbruik * brandstofprijs
        brandstof_per_maand = kosten_brandstof_per_jaar / 12
        rente_per_jaar = aanschafwaarde * (rente / 100)
        rente_per_maand = rente_per_jaar / 12
        
        # Totale kosten per jaar = afschrijving, brandstof, rente, verzekering (maand * 12) en rijtuigenbelasting (wb_numeric * 12)
        totale_kosten_per_jaar = (afschrijving_per_maand_calc * 12) + kosten_brandstof_per_jaar + rente_per_jaar + (verzekering_per_maand * 12) + (wb_numeric * 12)
        totale_kosten_per_maand = totale_kosten_per_jaar / 12
        
        # Bereken het verschil: Leaseprijs minus totale kosten per maand
        verschil = leaseprijs - totale_kosten_per_maand
        
        results.append({
            'Kenteken': kenteken,
            'Merk': merk,
            'Model': model,
            'Catalogusprijs': f"€ {float(catalogusprijs):,.2f}" if catalogusprijs and catalogusprijs != "Geen data gevonden" else "Niet gevonden",
            'Aanschafwaarde': f"€ {aanschafwaarde:,.2f}",
            'Afschrijvings %': f"{afschrijving_percentage:.2f}%",
            'Rijtuigenbelasting': f"€ {wb_numeric:,.2f}",
            'Brandstofverbruik': f"{verbruik:.2f} L/100km" if brandstof and "ELEKTR" not in brandstof.upper() else f"{verbruik:.2f} kWh/100km",
            'Kosten Brandstof per jaar': f"€ {kosten_brandstof_per_jaar:,.2f}",
            'Brandstof per maand': f"€ {brandstof_per_maand:.2f}",
            'Rente per jaar': f"€ {rente_per_jaar:,.2f}",
            'Rente per maand': f"€ {rente_per_maand:,.2f}",
            'Verzekering (p/m)': f"€ {verzekering_per_maand:,.2f}",
            'Totale kosten per jaar': f"€ {totale_kosten_per_jaar:,.2f}",
            'Totale kosten per maand': f"€ {totale_kosten_per_maand:,.2f}",
            'Leaseprijs (p/m)': f"€ {leaseprijs:,.2f}",
            'Verschil (Lease - Koop)': f"€ {verschil:,.2f}",
            # De kolommen die we later in de expander tonen:
            'Bouwjaar': bouwjaar,
            'Gewicht': f"{gewicht} kg" if gewicht and gewicht != "Geen data gevonden" else "Niet gevonden",
            'Kleur': kleur if kleur else "Onbekend",
            'APK': apk if apk else "Onbekend",
            'CO2': f"{co2} g/km" if co2 else "Onbekend",
            'Fijnstof': f"{fijnstof} mg/km" if fijnstof else "Onbekend",
            'Toelating': toelating
        })
    
    if results:
        # Maak eerst de hoofd-tabel zonder de verborgen kolommen
        df = pd.DataFrame(results)
        hidden_cols = ['Bouwjaar', 'Gewicht', 'Kleur', 'APK', 'CO2', 'Fijnstof', 'Toelating']
        df_main = df.drop(columns=hidden_cols)
        st.dataframe(df_main, use_container_width=True, hide_index=True)
        
        st.markdown("### Pas per auto de instellingen aan en bekijk extra details")
        # Voor iedere auto een expander met de instelvelden en extra (verborgen) details
        for res in results:
            kenteken = res['Kenteken']
            merk = res['Merk']
            model = res['Model']
            with st.expander(f"{merk} - {model} - {kenteken}"):
                # Aanpasbare velden
                new_aanschaf = st.number_input(
                    "Aanschafwaarde",
                    value=st.session_state.overrides.get(
                        f'aanschaf_{kenteken}', 
                        float(res['Aanschafwaarde'].replace("€", "").replace(",", "")) if res['Aanschafwaarde'] != "Niet gevonden" else 15000.00
                    ),
                    key=f"aanschaf_{kenteken}_exp"
                )
                st.session_state.overrides[f'aanschaf_{kenteken}'] = new_aanschaf

                new_afschrijving = st.number_input(
                    "Afschrijvingspercentage per jaar",
                    value=st.session_state.overrides.get(
                        f'afschrijving_{kenteken}', 
                        float(res['Afschrijvings %'].replace("%", "")) if res['Afschrijvings %'] != "Onbekend" else 12.0
                    ),
                    min_value=0.0, max_value=100.0,
                    key=f"afschrijving_{kenteken}_exp"
                )
                st.session_state.overrides[f'afschrijving_{kenteken}'] = new_afschrijving

                new_verzekering = st.number_input(
                    "Verzekering per maand",
                    value=st.session_state.overrides.get(
                        f'verzekering_{kenteken}', 
                        float(res['Verzekering (p/m)'].replace("€", "").replace(",", "")) if res['Verzekering (p/m)'] != "Niet gevonden" else 200.0
                    ),
                    min_value=0.0,
                    key=f"verzekering_{kenteken}_exp"
                )
                st.session_state.overrides[f'verzekering_{kenteken}'] = new_verzekering

                new_leaseprijs = st.number_input(
                    "Leaseprijs (p/m)",
                    value=st.session_state.overrides.get(
                        f'lease_{kenteken}', 
                        float(res['Leaseprijs (p/m)'].replace("€", "").replace(",", "")) if res['Leaseprijs (p/m)'] != "Niet gevonden" else 0.0
                    ),
                    min_value=0.0,
                    key=f"lease_{kenteken}_exp"
                )
                st.session_state.overrides[f'lease_{kenteken}'] = new_leaseprijs
                
                st.write("---")
                st.write("**Extra details:**")
                hidden_info = {col: res[col] for col in hidden_cols}
                st.table(pd.DataFrame(hidden_info, index=[0]))
    else:
        st.error("Geen geldige resultaten gevonden voor de ingevoerde kentekens.")

#########################################
# Sla de data veilig op wanneer de app opnieuw rendert
#########################################
save_persistent_data()
