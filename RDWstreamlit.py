import streamlit as st
import requests
import pandas as pd
from typing import Dict, Any

def get_wegenbelasting(massa_rijklaar, brandstof):
    """Berekent de wegenbelasting op basis van het gewicht en het brandstoftype."""
    # Als het voertuig elektrisch is, geldt geen wegenbelasting
    if "elektr" in brandstof.lower():
        return 0
    
    if massa_rijklaar <= 950:
        base = 30
    elif massa_rijklaar <= 2050:
        base = 80
    else:
        base = 100
    
    if brandstof.lower() == 'diesel':
        return base * 2
    elif brandstof.lower() == 'lpg':
        return base * 1.5
    else:
        return base

def get_car_info(kenteken: str) -> Dict[str, Any]:
    """Haal auto-informatie op via de RDW API."""
    kenteken = kenteken.upper().replace('-', '').strip()
    
    base_url = f"https://opendata.rdw.nl/resource/m9d7-ebf2.json?kenteken={kenteken}"
    response = requests.get(base_url)
    if not response.ok or not response.json():
        return None
    
    car_data = response.json()[0]
    
    # Haal de brandstofinformatie op
    brandstof_url = f"https://opendata.rdw.nl/resource/8ys7-d773.json?kenteken={kenteken}"
    brandstof_response = requests.get(brandstof_url)
    if brandstof_response.ok and brandstof_response.json():
        car_data['brandstof'] = brandstof_response.json()[0]['brandstof_omschrijving']
    else:
        car_data['brandstof'] = 'Onbekend'
    
    return car_data

def calculate_costs(car_info: Dict[str, Any], params: Dict[str, float], overrides: Dict[str, float] = None) -> Dict[str, Any]:
    """Bereken alle kosten voor een auto over 48 maanden."""
    if not car_info:
        return None
    if overrides is None:
        overrides = {}
    
    catalogusprijs = float(car_info.get('catalogusprijs', 0))
    massa_rijklaar = float(car_info.get('massa_rijklaar', 0))
    brandstof = car_info.get('brandstof', 'Onbekend')
    kenteken = car_info.get('kenteken', 'Onbekend')
    
    # Afschrijving
    afschrijving_percentage = overrides.get(f'afschrijving_{kenteken}', params['afschrijving_percentage'])
    afschrijving = (catalogusprijs * (afschrijving_percentage / 100) / 12) * 48
    
    # Wegenbelasting
    wegenbelasting_basis = get_wegenbelasting(massa_rijklaar, brandstof)
    wegenbelasting = overrides.get(f'wegenbelasting_{kenteken}', wegenbelasting_basis) * 48
    
    jaarlijkse_km = params['jaarlijkse_km']
    
    # Bereken brandstof- of energie-kosten
    if "elektr" in brandstof.lower():
        # Voor elektrische auto's: gebruik kWh-prijs en elektrische efficiëntie (km per kWh)
        electric_efficiency = overrides.get(f'electric_efficiency_{kenteken}', params['electric_efficiency'])
        electric_kwh_price = overrides.get(f'electric_kwh_price_{kenteken}', params['electric_kwh_price'])
        # Jaarlijks verbruik in kWh = kilometers / (km per kWh)
        annual_kwh = jaarlijkse_km / electric_efficiency
        brandstofkosten_jaar = annual_kwh * electric_kwh_price
        brandstofkosten = brandstofkosten_jaar * 4
    else:
        # Voor voertuigen op fossiele brandstoffen
        brandstof_verbruik = overrides.get(f'brandstof_verbruik_{kenteken}', params['brandstof_verbruik'])
        brandstofkosten_jaar = (jaarlijkse_km / 100) * brandstof_verbruik * params['brandstof_prijs']
        brandstofkosten = brandstofkosten_jaar * 4
    
    # Rentederving
    rentederving = catalogusprijs * (params['rentederving_percentage'] / 100) * 4
    
    # Verzekering
    verzekering_basis = overrides.get(f'verzekering_{kenteken}', params['basis_verzekering'])
    verzekering_jaar = verzekering_basis * (1 - min(params['schadevrije_jaren'] * 0.03, 0.30))
    verzekering = verzekering_jaar * 4
    
    totaal = afschrijving + wegenbelasting + brandstofkosten + rentederving + verzekering
    
    return {
        'kenteken': kenteken,
        'merk': car_info.get('merk', 'Onbekend'),
        'model': car_info.get('handelsbenaming', 'Onbekend'),
        'catalogusprijs': catalogusprijs,
        'brandstoftype': brandstof,
        'afschrijving': afschrijving,
        'wegenbelasting': wegenbelasting,
        'brandstofkosten': brandstofkosten,
        'rentederving': rentederving,
        'verzekering': verzekering,
        'totaal': totaal,
        # Overzicht van de gebruikte parameters:
        'afschrijving_percentage': afschrijving_percentage,
        'wegenbelasting_basis': overrides.get(f'wegenbelasting_{kenteken}', wegenbelasting_basis),
        'brandstof_verbruik': overrides.get(f'brandstof_verbruik_{kenteken}', params.get('brandstof_verbruik')),
        'electric_efficiency': overrides.get(f'electric_efficiency_{kenteken}', params.get('electric_efficiency')),
        'electric_kwh_price': overrides.get(f'electric_kwh_price_{kenteken}', params.get('electric_kwh_price')),
        'verzekering_basis': verzekering_basis
    }

# Initialiseer session state variabelen
if 'overrides' not in st.session_state:
    st.session_state.overrides = {}
if 'cars_info' not in st.session_state:
    st.session_state.cars_info = {}

st.set_page_config(layout="wide")
st.title("🚗 Autokosten Calculator")
st.write("""
Deze applicatie berekent de kosten van auto's over een periode van 48 maanden.
Voer hieronder één of meerdere kentekens in (één per regel).
""")

# Parameters in de sidebar
st.sidebar.header("Algemene Parameters")
params = {
    'afschrijving_percentage': st.sidebar.number_input("Standaard afschrijving per jaar (%)", value=12.0, min_value=0.0, max_value=100.0),
    'brandstof_verbruik': st.sidebar.number_input("Standaard brandstofverbruik (L/100km)", value=6.5, min_value=0.0),
    'jaarlijkse_km': st.sidebar.number_input("Jaarlijkse kilometers", value=15000, min_value=0),
    'brandstof_prijs': st.sidebar.number_input("Brandstofprijs per liter (€)", value=1.8, min_value=0.0),
    'rentederving_percentage': st.sidebar.number_input("Rentederving per jaar (%)", value=5.0, min_value=0.0),
    'basis_verzekering': st.sidebar.number_input("Standaard verzekeringspremie per jaar (€)", value=600.0, min_value=0.0),
    'schadevrije_jaren': st.sidebar.number_input("Aantal schadevrije jaren", value=5, min_value=0),
    # Nieuwe parameters voor elektrische auto's:
    'electric_kwh_price': st.sidebar.number_input("Elektriciteitsprijs per kWh (€)", value=0.30, min_value=0.0),
    'electric_efficiency': st.sidebar.number_input("Elektrische efficiëntie (km per kWh)", value=6.0, min_value=0.0)
}

budget = st.sidebar.number_input("Budget voor 48 maanden (€)", value=20000.0, min_value=0.0)

# Invoer voor kentekens
kentekens = st.text_area("Voer kentekens in (één per regel):", height=100)

if kentekens:
    kenteken_list = [k.strip().upper() for k in kentekens.split('\n') if k.strip()]
    
    # Haal per kenteken de auto-informatie op
    progress_bar = st.progress(0)
    for i, kenteken in enumerate(kenteken_list):
        if kenteken not in st.session_state.cars_info:
            st.session_state.cars_info[kenteken] = get_car_info(kenteken)
        progress_bar.progress((i + 1) / len(kenteken_list))
    
    # Bereken de resultaten voor elke auto
    results = []
    for kenteken, car_info in st.session_state.cars_info.items():
        if car_info:
            result = calculate_costs(car_info, params, st.session_state.overrides)
            if result:
                results.append(result)
    
    if results:
        # Zet de resultaten in een DataFrame en formatteer valuta-kolommen
        df = pd.DataFrame(results)
        currency_cols = ['catalogusprijs', 'afschrijving', 'wegenbelasting', 
                         'brandstofkosten', 'rentederving', 'verzekering', 'totaal']
        df_display = df.copy()
        for col in currency_cols:
            df_display[col] = df_display[col].apply(lambda x: f"€ {x:,.2f}")
        
        st.header("📊 Resultaten")
        st.dataframe(df_display, use_container_width=True, hide_index=True)
        
        st.header("Individuele Aanpassingen")
        # Voor iedere auto een expander met aanpasbare parameters
        for kenteken, car_info in st.session_state.cars_info.items():
            if car_info:
                with st.expander(f"{car_info.get('merk', 'Onbekend')} {car_info.get('handelsbenaming', 'Onbekend')} ({kenteken})"):
                    st.session_state.overrides[f'afschrijving_{kenteken}'] = st.number_input(
                        "Afschrijving % per jaar",
                        value=st.session_state.overrides.get(f'afschrijving_{kenteken}', params['afschrijving_percentage']),
                        key=f"afschr_{kenteken}"
                    )
                    st.session_state.overrides[f'wegenbelasting_{kenteken}'] = st.number_input(
                        "Wegenbelasting per maand",
                        value=st.session_state.overrides.get(
                            f'wegenbelasting_{kenteken}', 
                            get_wegenbelasting(float(car_info['massa_rijklaar']), car_info['brandstof'])
                        ),
                        key=f"bel_{kenteken}"
                    )
                    if "elektr" in car_info['brandstof'].lower():
                        st.session_state.overrides[f'electric_efficiency_{kenteken}'] = st.number_input(
                            "Elektrische efficiëntie (km per kWh)",
                            value=st.session_state.overrides.get(f'electric_efficiency_{kenteken}', params['electric_efficiency']),
                            key=f"electric_efficiency_{kenteken}"
                        )
                        st.session_state.overrides[f'electric_kwh_price_{kenteken}'] = st.number_input(
                            "Elektriciteitsprijs per kWh (€)",
                            value=st.session_state.overrides.get(f'electric_kwh_price_{kenteken}', params['electric_kwh_price']),
                            key=f"electric_kwh_price_{kenteken}"
                        )
                    else:
                        st.session_state.overrides[f'brandstof_verbruik_{kenteken}'] = st.number_input(
                            "Brandstofverbruik (L/100km)",
                            value=st.session_state.overrides.get(f'brandstof_verbruik_{kenteken}', params['brandstof_verbruik']),
                            key=f"fuel_{kenteken}"
                        )
                    st.session_state.overrides[f'verzekering_{kenteken}'] = st.number_input(
                        "Verzekeringspremie per jaar (€)",
                        value=st.session_state.overrides.get(f'verzekering_{kenteken}', params['basis_verzekering']),
                        key=f"verz_{kenteken}"
                    )
        
        # Downloadknop voor de resultaten als CSV
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "⬇️ Download resultaten als CSV",
            csv,
            "autokosten_berekening.csv",
            "text/csv",
            key='download-csv'
        )
    else:
        st.error("Geen geldige resultaten gevonden voor de ingevoerde kentekens.")
