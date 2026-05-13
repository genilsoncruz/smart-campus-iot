## URL Firebase: https://console.firebase.google.com/project/smart-campus-iot-2bd80/database/smart-campus-iot-2bd80-default-rtdb/data

## URL Postman: https://restless-flare-1222.postman.co/workspace/GPS_CO2~8f170ee2-419c-4836-b1b7-5bb5e6a183ff/collection/7375360-f3569083-130e-4bec-8863-cb1ef5ce4ddd

## Deploying to Streamlit

To run this application, follow these steps:

1.  **Save the code:** Copy the Python code from the cell below and save it as `app.py` on your local machine.

2.  **Create `requirements.txt`:** Create a file named `requirements.txt` in the same directory as `app.py` with the following content:

    ```
    streamlit
    pandas
    requests
    geopandas
    folium
    shapely
    branca
    streamlit-folium
    ipywidgets # Although ipywidgets are replaced, some underlying dependencies might expect it
    ```

3.  **Install dependencies:** Open your terminal or command prompt, navigate to the directory where you saved `app.py` and `requirements.txt`, and run:

    ```bash
    pip install -r requirements.txt
    ```

4.  **Run the app locally:** Execute the Streamlit app with the command:

    ```bash
    streamlit run app.py
    ```

    This will open the app in your web browser.

5.  **Deploy to Streamlit Cloud:**
    *   Push your `app.py` and `requirements.txt` files to a public GitHub repository.
    *   Go to [Streamlit Cloud](https://share.streamlit.io/).
    *   Log in and click "New app" to connect your GitHub repository and deploy your application.
