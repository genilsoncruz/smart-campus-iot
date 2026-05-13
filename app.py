import streamlit as st
import pandas as pd
import requests
import geopandas as gpd
import folium
from shapely.geometry import Point
from folium.plugins import HeatMap
from branca.colormap import linear
from streamlit_folium import folium_static
import io
import numpy as np
from scipy.spatial.distance import cdist
from sklearn.linear_model import LinearRegression
import plotly.graph_objects as go

# --- Configuration ---
st.set_page_config(
    page_title="Monitoramento de CO₂",
    page_icon="🌍",
    layout="wide"
)

# --- Constants ---
FIREBASE_URL = "https://smart-campus-iot-2bd80-default-rtdb.firebaseio.com/dados.json"

# URLs para dados geográficos
URL_GEOJSON_MUNICIPIOS = "https://servicodados.ibge.gov.br/api/v3/malhas/estados/32?formato=application/json&intrarregiao=municipio"
URL_NOMES_MUNICIPIOS = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/32/municipios"

# --- Data Loading (Cached) ---
@st.cache_data(ttl=600) # Cache data for 10 minutes
def load_data():
    # 1. Consuming data from Firebase
    try:
        response = requests.get(FIREBASE_URL)
        response.raise_for_status() # Raise an exception for HTTP errors
        dados = response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Erro ao carregar dados do Firebase: {e}")
        return None

    # 2. Converting to DataFrame
    registros = []
    for chave, valor in dados.items():
        if isinstance(valor, dict) and "gps" in valor:
            registro = {
                "id": chave,
                "device": valor.get("device", "desconhecido"),
                "lat": valor["gps"]["lat"],
                "lng": valor["gps"]["lng"],
                "alt": valor["gps"].get("alt", 0),
                "speed": valor["gps"].get("speed", 0),
                "co2": valor["co2"]["ppm"],
                "timestamp": valor.get("timestamp", 0)
            }
            registros.append(registro)

    if not registros:
        st.warning("Nenhum registro encontrado no Firebase.")
        return None

    df = pd.DataFrame(registros)

    # 3. Converting timestamps
    df["datetime"] = pd.to_datetime(
        df["timestamp"],
        unit="s",
        errors="coerce"
    )

    # 4. Converting GPS points to GeoDataFrame
    geometry = [
        Point(xy)
        for xy in zip(df["lng"], df["lat"])
    ]
    gdf = gpd.GeoDataFrame(
        df,
        geometry=geometry,
        crs="EPSG:4326"
    )

    # 5. Loading municipal boundaries from IBGE
    try:
        res_malha = requests.get(URL_GEOJSON_MUNICIPIOS)
        res_nomes = requests.get(URL_NOMES_MUNICIPIOS)
        res_malha.raise_for_status()
        res_nomes.raise_for_status()

        municipios = gpd.read_file(io.BytesIO(res_malha.content))
        # Explicitly set CRS if it's not detected or is None
        if municipios.crs is None:
            municipios.set_crs("EPSG:4326", inplace=True) # Assuming GeoJSON is WGS84

        dados_nomes = res_nomes.json()
        mapa_nomes = {str(item['id']): item['nome'] for item in dados_nomes}
        municipios['nome'] = municipios['codarea'].map(lambda x: mapa_nomes.get(str(x)))

        # Reproject municipios to match gdf's CRS before spatial join
        municipios = municipios.to_crs(gdf.crs)

    except requests.exceptions.RequestException as e:
        st.error(f"Erro ao carregar dados municipais do IBGE: {e}")
        return None

    # 6. Relating points to municipalities
    gdf_join = gpd.sjoin(
        gdf,
        municipios,
        how="left",
        predicate="within"
    )

    return gdf_join

# --- Filtering Function ---
def filtrar_dados(gdf_join, selected_devices, selected_municipios, co2_min, co2_max, data_inicio, data_fim):
    filtrado = gdf_join.copy()

    if selected_devices:
        filtrado = filtrado[filtrado["device"].isin(selected_devices)]

    if selected_municipios:
        filtrado = filtrado[filtrado["nome"].isin(selected_municipios)]

    filtrado = filtrado[
        (filtrado["co2"] >= co2_min) &
        (filtrado["co2"] <= co2_max)
    ]

    if data_inicio:
        filtrado = filtrado[filtrado["datetime"] >= pd.Timestamp(data_inicio)]

    if data_fim:
        filtrado = filtrado[filtrado["datetime"] <= pd.Timestamp(data_fim)]

    return filtrado

# --- Map Generation Functions ---
def gerar_mapa(filtered_gdf):
    if filtered_gdf.empty:
        st.warning("Nenhum dado encontrado para o mapa de marcadores.")
        return None

    centro_lat = filtered_gdf["lat"].mean()
    centro_lng = filtered_gdf["lng"].mean()

    if pd.isna(centro_lat) or pd.isna(centro_lng):
        st.error("Não foi possível determinar o centro do mapa para marcadores.")
        return None

    mapa = folium.Map(
        location=[centro_lat, centro_lng],
        zoom_start=12
    )

    min_co2 = filtered_gdf["co2"].min()
    max_co2 = filtered_gdf["co2"].max()

    if min_co2 == max_co2:
        colormap = linear.YlOrRd_09.scale(min_co2 - 1, max_co2 + 1) # Avoid division by zero if all values are the same
    else:
        colormap = linear.YlOrRd_09.scale(min_co2, max_co2)

    for _, row in filtered_gdf.iterrows():
        cor = colormap(row["co2"])
        tamanho = row["co2"] / 50 # Adjust size based on CO2 value

        popup_html = f"""
        <b>Dispositivo:</b> {row.get('device', 'N/A')}<br>
        <b>Município:</b> {row.get('nome', 'N/A')}<br>
        <b>CO₂:</b> {row.get('co2', 'N/A')} ppm<br>
        <b>Data:</b> {row.get('datetime', 'N/A')}<br>
        """

        folium.CircleMarker(
            location=[row["lat"], row["lng"]],
            radius=max(1, tamanho), # Ensure radius is at least 1
            popup=folium.Popup(popup_html, max_width=300),
            color=cor,
            fill=True,
            fill_color=cor,
            fill_opacity=0.7
        ).add_to(mapa)

    colormap.caption = "CO₂ ppm"
    colormap.add_to(mapa)

    return mapa

def gerar_heatmap(filtered_gdf):
    if filtered_gdf.empty:
        st.warning("Nenhum dado encontrado para o mapa de calor.")
        return None

    # Remove registros inválidos
    filtrado_heatmap = filtered_gdf.dropna(subset=["lat", "lng", "co2"])

    if filtrado_heatmap.empty:
        st.warning("Nenhum dado válido encontrado para o mapa de calor.")
        return None

    centro_lat = filtrado_heatmap["lat"].mean()
    centro_lng = filtrado_heatmap["lng"].mean()

    if pd.isna(centro_lat) or pd.isna(centro_lng):
        st.error("Não foi possível determinar o centro do mapa de calor.")
        return None

    mapa_heatmap = folium.Map(
        location=[centro_lat, centro_lng],
        zoom_start=12
    )

    heat_data = [
        [row["lat"], row["lng"], row["co2"]]
        for _, row in filtrado_heatmap.iterrows()
        if pd.notna(row["lat"]) and pd.notna(row["lng"])
    ]

    if not heat_data:
        st.warning("Sem dados suficientes para gerar o heatmap.")
        return None

    HeatMap(
        heat_data,
        radius=25,
        blur=20
    ).add_to(mapa_heatmap)

    return mapa_heatmap

# --- Prediction Functions ---
def generate_temporal_prediction(filtered_gdf, device_name, prediction_horizon):
    device_data = filtered_gdf[filtered_gdf['device'] == device_name].copy()
    device_data = device_data.sort_values('datetime')
    device_data = device_data.set_index('datetime')

    if device_data.empty:
        st.warning(f"Nenhum dado para o dispositivo '{device_name}' no período filtrado. Não é possível gerar previsão temporal.")
        return pd.DataFrame(), None

    if len(device_data) < 2:
        st.warning(f"Dados insuficientes para prever a evolução temporal para o dispositivo '{device_name}'. Mínimo de 2 pontos necessários.")
        return pd.DataFrame(), None

    device_data['time_numeric'] = (device_data.index - device_data.index.min()).total_seconds()

    X = device_data['time_numeric'].values.reshape(-1, 1)
    y = device_data['co2'].values

    try:
        model = LinearRegression()
        model.fit(X, y)
    except Exception as e:
        st.error(f"Erro ao treinar o modelo de regressão para {device_name}: {e}")
        return pd.DataFrame(), None

    # Predict future values
    last_time = device_data['time_numeric'].max()
    future_timestamps = pd.date_range(start=device_data.index.max(), periods=prediction_horizon + 1, freq='H')[1:]
    future_time_numeric = (future_timestamps - device_data.index.min()).total_seconds().values.reshape(-1, 1)
    predicted_co2 = model.predict(future_time_numeric)

    prediction_df = pd.DataFrame({
        'datetime': future_timestamps,
        'co2': predicted_co2
    })

    # Combine historical and predicted for plotting
    plot_df = pd.concat([
        device_data[['co2']].reset_index(),
        prediction_df
    ])

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=device_data.index, y=device_data['co2'], mode='lines+markers', name='CO₂ Histórico'))
    fig.add_trace(go.Scatter(x=prediction_df['datetime'], y=prediction_df['co2'], mode='lines+markers', name='CO₂ Previsto', line=dict(dash='dash')))
    fig.update_layout(title=f'Previsão Temporal de CO₂ para Dispositivo {device_name}',
                      xaxis_title='Data/Hora', yaxis_title='Nível de CO₂ (ppm)')

    return plot_df, fig

def predict_spatial_co2_idw(filtered_gdf, target_lat, target_lng, power=2, num_neighbors=None):
    # Ensure filtered_gdf is not empty and has necessary columns
    if filtered_gdf.empty or not all(col in filtered_gdf.columns for col in ['lat', 'lng', 'co2']):
        return None, "Nenhum dado de sensor válido disponível para predição espacial após filtragem."

    # Filter out any rows with NaN in critical columns
    sensor_data_for_idw = filtered_gdf.dropna(subset=['lat', 'lng', 'co2'])

    if sensor_data_for_idw.empty:
        return None, "Nenhum dado de sensor válido após remover valores ausentes para predição espacial."

    sensor_coords = sensor_data_for_idw[['lat', 'lng']].values
    sensor_co2 = sensor_data_for_idw['co2'].values
    target_coord = np.array([[target_lat, target_lng]])

    # Check if target coordinates are valid
    if not (np.isfinite(target_lat) and np.isfinite(target_lng)):
        return None, "Coordenadas do ponto alvo inválidas."

    # Calculate distances. Add a small epsilon to avoid division by zero if target_coord is identical to a sensor_coord
    # This case is handled below more explicitly, but defensive programming helps.
    distances = cdist(sensor_coords, target_coord).flatten()

    # Handle cases where target is exactly at a sensor location
    if np.any(distances < 1e-6): # Using a small threshold for 'equals zero'
        idx = np.argmin(distances) # Get index of the closest (effectively zero) distance
        return sensor_co2[idx], f"Ponto alvo coincide com um sensor existente (CO₂: {sensor_co2[idx]:.2f} ppm)."

    # Ensure num_neighbors doesn't exceed available sensors
    actual_num_neighbors = len(sensor_data_for_idw)
    if num_neighbors is None or num_neighbors > actual_num_neighbors:
        num_neighbors = actual_num_neighbors # Use all available if not specified or too high

    if num_neighbors < 1: # Must have at least one neighbor for IDW
        return None, "Número insuficiente de vizinhos para interpolação IDW."

    # Select neighbors if specified and data allows
    if num_neighbors < actual_num_neighbors:
        closest_indices = np.argsort(distances)[:num_neighbors]
        distances = distances[closest_indices]
        sensor_co2 = sensor_co2[closest_indices]

    # Calculate weights based on inverse distance
    # Handle case where distances might still be very small if not exactly zero
    if np.any(distances == 0):
        # This should ideally be caught by the 1e-6 check, but as a safeguard
        return None, "Distância zero encontrada após filtragem, mas não tratada como ponto idêntico. Verifique dados."

    weights = 1 / (distances ** power)

    # Normalize weights
    sum_of_weights = np.sum(weights)
    if sum_of_weights == 0:
        return None, "Não foi possível calcular pesos (soma dos pesos é zero)."

    normalized_weights = weights / sum_of_weights

    # Predict CO2
    predicted_co2 = np.sum(normalized_weights * sensor_co2)

    return predicted_co2, None


# --- Streamlit App Layout ---
st.title("🌍 Monitoramento de CO₂ em Tempo Real")
st.markdown("Dashboard interativo para visualizar dados de CO₂ de dispositivos IoT.")

# Load initial data
gdf_join = load_data()

if gdf_join is None or gdf_join.empty:
    st.stop() # Stop if no data is loaded

# Get unique values for filters
devices = sorted(gdf_join["device"].dropna().unique().tolist())
municipios_lista = sorted(gdf_join["nome"].dropna().unique().tolist())

# Sidebar for Filters
st.sidebar.header("Filtros de Dados")

selected_devices = st.sidebar.multiselect(
    "Dispositivos",
    options=devices,
    default=devices,
    help="Selecione um ou mais dispositivos para filtrar."
)

selected_municipios = st.sidebar.multiselect(
    "Municípios",
    options=municipios_lista,
    default=municipios_lista,
    help="Selecione um ou mais municípios para filtrar."
)

# CO2 Slider
min_co2_val = int(gdf_join["co2"].min()) if not gdf_join.empty else 0
max_co2_val = int(gdf_join["co2"].max()) if not gdf_join.empty else 1000

# Adjust min_value and max_value for the slider if they are equal
# to avoid "min_value must be less than max_value" error
slider_min_val = min_co2_val
slider_max_val = max_co2_val

if min_co2_val == max_co2_val:
    # If min and max are the same, expand the slider's range slightly
    # to allow the slider to function, e.g., +/- 5 around the value
    slider_min_val = max(0, min_co2_val - 5)
    slider_max_val = max_co2_val + 5
    # Ensure slider_min_val is always less than slider_max_val
    if slider_min_val == slider_max_val:
        slider_max_val += 1 # Ensure difference

# Prevent error if initial data makes slider_min_val >= slider_max_val (e.g., if only one data point or weird data)
if slider_min_val >= slider_max_val:
    slider_max_val = slider_min_val + 1

co2_range = st.sidebar.slider(
    "Nível de CO₂ (ppm)",
    min_value=slider_min_val,
    max_value=slider_max_val,
    value=(min_co2_val, max_co2_val), # Default selected range
    step=10,
    help="Ajuste o intervalo de CO₂."
)
co2_min, co2_max = co2_range

# Date Pickers
min_date_data = gdf_join["datetime"].min().date() if not gdf_join.empty else pd.to_datetime('2023-01-01').date()
max_date_data = gdf_join["datetime"].max().date() if not gdf_join.empty else pd.to_datetime('2024-12-31').date()

selected_date_range = st.sidebar.date_input(
    "Período",
    value=(min_date_data, max_date_data),
    min_value=min_date_data,
    max_value=max_date_data,
    help="Selecione o intervalo de datas."
)

data_inicio = None
data_fim = None
if len(selected_date_range) == 2:
    data_inicio = selected_date_range[0]
    data_fim = selected_date_range[1]
elif len(selected_date_range) == 1:
    data_inicio = selected_date_range[0]
    data_fim = selected_date_range[0]


# Apply filters
filtered_gdf = filtrar_dados(
    gdf_join,
    selected_devices,
    selected_municipios,
    co2_min,
    co2_max,
    data_inicio,
    data_fim
)

st.subheader("Estatísticas Analíticas")
if filtered_gdf.empty:
    st.warning("Nenhum dado corresponde aos filtros selecionados.")
else:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Quantidade de Registros", len(filtered_gdf))
    col2.metric("CO₂ Médio (ppm)", f"{filtered_gdf['co2'].mean():.2f}")
    col3.metric("CO₂ Máximo (ppm)", filtered_gdf['co2'].max())
    col4.metric("CO₂ Mínimo (ppm)", filtered_gdf['co2'].min())

st.markdown("--- ")

st.subheader("Visualização e Predição")

tab1, tab2, tab3, tab4 = st.tabs(["Mapa de Marcadores", "Mapa de Calor", "Previsão Temporal", "Previsão Espacial"])

with tab1:
    st.markdown("### Mapa de Marcadores de CO₂")
    mapa_marcadores = gerar_mapa(filtered_gdf)
    if mapa_marcadores:
        folium_static(mapa_marcadores, width=700, height=500)

with tab2:
    st.markdown("### Mapa de Calor de CO₂")
    mapa_calor = gerar_heatmap(filtered_gdf)
    if mapa_calor:
        folium_static(mapa_calor, width=700, height=500)

with tab3:
    st.markdown("### Previsão Temporal da Evolução de CO₂")
    st.warning("A precisão desta previsão é altamente dependente da quantidade e variedade dos dados históricos disponíveis.")

    if not devices:
        st.info("Nenhum dispositivo disponível para previsão temporal.")
    else:
        # Filtered devices based on actual data present in filtered_gdf for prediction
        available_devices_for_temporal = filtered_gdf['device'].dropna().unique().tolist()
        if not available_devices_for_temporal:
            st.info("Nenhum dispositivo com dados suficientes no período filtrado para previsão temporal.")
        else:
            temporal_device_selection = st.selectbox("Selecione um dispositivo para previsão", options=available_devices_for_temporal)
            prediction_horizon = st.slider("Horizonte de previsão (horas)", min_value=1, max_value=24, value=6)

            if st.button("Gerar Previsão Temporal"):
                if temporal_device_selection:
                    plot_df, fig_temporal = generate_temporal_prediction(filtered_gdf, temporal_device_selection, prediction_horizon)
                    if fig_temporal:
                        st.plotly_chart(fig_temporal, use_container_width=True)
                    elif not plot_df.empty:
                        st.write("Dados para previsão:", plot_df)

with tab4:
    st.markdown("### Predição de CO₂ em Ponto Não Medido (IDW)")
    st.warning("A precisão desta predição depende da distribuição dos sensores e da variabilidade dos dados. Com poucos pontos, a previsão pode ser imprecisa.")

    # Ensure filtered_gdf has enough points and valid data for spatial prediction
    valid_sensors_for_idw = filtered_gdf.dropna(subset=['lat', 'lng', 'co2'])
    if valid_sensors_for_idw.empty:
        st.info("Nenhum dado válido para realizar a predição espacial após filtragem de valores ausentes.")
    elif len(valid_sensors_for_idw) < 1: # Need at least one sensor for IDW to make sense
        st.info("Dados insuficientes para realizar a predição espacial (mínimo de 1 sensor com lat/lng/CO2 válido necessário).")
    else:
        st.markdown("#### Informe as coordenadas do ponto para previsão:")
        default_lat = valid_sensors_for_idw['lat'].mean() if not valid_sensors_for_idw.empty else -20.3155
        default_lng = valid_sensors_for_idw['lng'].mean() if not valid_sensors_for_idw.empty else -40.3128

        target_lat = st.number_input("Latitude", value=float(f'{default_lat:.4f}'), format="%.4f")
        target_lng = st.number_input("Longitude", value=float(f'{default_lng:.4f}'), format="%.4f")
        idw_power = st.slider("Potência de IDW (p)", min_value=1.0, max_value=5.0, value=2.0, step=0.1, help="Maior valor de 'p' dá mais peso a pontos próximos.")

        # Dynamically set max_value for idw_neighbors based on available sensors
        max_neighbors_possible = len(valid_sensors_for_idw)
        
        if max_neighbors_possible < 2: # If 0 or 1 valid sensors, hide slider and inform user
            if max_neighbors_possible == 0:
                st.info("Nenhum sensor disponível para interpolação IDW. Ajuste os filtros para incluir sensores.")
            else: # max_neighbors_possible == 1
                st.info("Apenas 1 sensor disponível. A predição espacial utilizará o valor deste sensor.")
            idw_neighbors = 1 # Set default, non-interactive value
            st.text(f"Vizinhos considerados: {idw_neighbors}")
        else: # max_neighbors_possible >= 2, so a slider is appropriate
            current_idw_neighbors = st.session_state.get('idw_neighbors_value', min(3, max_neighbors_possible))
            idw_neighbors = st.slider(
                "Número de vizinhos para IDW",
                min_value=1,
                max_value=max_neighbors_possible,
                value=min(current_idw_neighbors, max_neighbors_possible),
                help="Número de sensores mais próximos a considerar na interpolação.",
                key='idw_neighbors_value'
            )

        if st.button("Calcular Predição Espacial"):
            predicted_co2, error_message = predict_spatial_co2_idw(valid_sensors_for_idw, target_lat, target_lng, power=idw_power, num_neighbors=idw_neighbors)
            if error_message:
                st.error(error_message)
            elif predicted_co2 is not None:
                st.success(f"**CO₂ Previsto no ponto ({target_lat:.4f}, {target_lng:.4f}): {predicted_co2:.2f} ppm**")

                # Visualize the predicted point on a map
                # Ensure default_lat/lng are used for map if filtered_gdf is truly empty or all NaN
                map_center_lat = filtered_gdf['lat'].mean() if not filtered_gdf.empty else -20.3155
                map_center_lng = filtered_gdf['lng'].mean() if not filtered_gdf.empty else -40.3128

                mapa_spatial = folium.Map(location=[map_center_lat, map_center_lng], zoom_start=12)
                folium.Marker(
                    location=[target_lat, target_lng],
                    popup=f"CO₂ Previsto: {predicted_co2:.2f} ppm",
                    icon=folium.Icon(color='red', icon='info-sign')
                ).add_to(mapa_spatial)

                # Add existing sensor points
                for _, row in valid_sensors_for_idw.iterrows(): # Use valid_sensors_for_idw here
                    folium.CircleMarker(
                        location=[row["lat"], row["lng"]],
                        radius=5,
                        popup=f"Device: {row['device']}, CO₂: {row['co2']} ppm",
                        color='blue',
                        fill=True,
                        fill_color='blue',
                        fill_opacity=0.7
                    ).add_to(mapa_spatial)

                folium_static(mapa_spatial, width=700, height=500)
            else:
                st.info("Não foi possível gerar a previsão espacial. Verifique os dados e os parâmetros.")

st.markdown("--- ")
st.info("Dados atualizados a cada 10 minutos.")