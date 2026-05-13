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