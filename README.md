<p align="center">
  <img src="https://www.widsworldwide.org/wp-content/uploads/2023/05/WiDS_logo_nav.png" alt="WiDS Logo" width="250"/>
</p>

<h1 align="center">WiDS Datathon 2026 – Student Submission Template</h1>

Welcome to your project workspace for the WiDS Datathon 2026! This repository serves as your final submission for grading and sharing. All analysis should be done in Google Colab, and your final results will be presented in a standalone slide deck.

---

## Getting Started

### 1. Clone or Fork this Repository
Click the **Fork** button at the top-right of this page to create your own copy under your GitHub account.

### 2. Edit the Notebook in Colab  
Click below to open the notebook directly in Google Colab:  
[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](notebook.ipynb)

- Do all data cleaning, EDA, modeling, and analysis in the notebook.  
- Use Markdown cells to explain each step.

---

## Problem Statement

This year’s WiDS Datathon challenge offers **two powerful routes**. Each one addresses real-world problems caused by wildfires. Your team must choose **ONE** route and clearly indicate your choice in both your notebook and slide presentation.

---

### 🔹 Route 1: Accelerating Equitable Evacuations

**Core Question:**  
*How can we reduce delays in evacuation alerts and improve response times for the communities that are most at risk?*

This route focuses on analyzing how and when evacuation alerts are triggered — and how we can improve timeliness and fairness in communication, especially for vulnerable populations.

**Suggested Starting Points:**
- Compare `date_modified` and `effective` fields in WatchDuty to identify alert lags.
- Integrate NOAA weather data (wind, humidity) to model fire spread and shrinking evacuation windows.
- Map low-mobility zones (e.g. road access, car ownership) against health vulnerabilities (e.g. asthma, elderly population).
- Build a risk surface using perimeter snapshots, alert timestamps, and report logs to assess delays.
- Use `timestamp_reported` and classification reports to study "pending" alerts and delays.

**Why this matters:**  
Improved risk dashboards, real-time alerts, and support systems for people with disabilities, pets, or other special needs.

---

### 🔹 Route 2: Designing for Economic Resilience

**Core Question:**  
*How can wildfire disruption analytics inform stronger economic safety nets for affected workers, families, and small businesses?*

This route is about quantifying how wildfires affect employment, income, and tourism — and using that insight to design better protections for vulnerable communities.

**Suggested Starting Points:**
- Use `geo_event_type` and evacuation zones to estimate lost workdays and industry impact.
- Overlay fire risk maps with labor statistics to simulate “fire leave” policy impacts.
- Map wildfire frequency against Airbnb density and seasonal tourism data to assess local economic fragility.
- Explore long-term effects like secondary illness, displacement, or financial strain.

**Why this matters:**  
Supports for gig workers, targeted aid for small businesses, and policy tools for economic recovery.

---

**Clearly state your chosen route at the top of your notebook and slide deck.** Your work should combine **data analysis**, **modeling**, and **real-world relevance** to propose actionable insights.

---

## Project Title & Team Info

**Project Title**: _BEACON: Broadscale Evacuation Agentic Coordination, Outreach, and Navigation_  
**Team Name**: _Wildfire Equitable Collective_  
**University**: _University of San Francisco_  
**Course**: _Master's in Data Science and AI_  
**Term**: _Spring 2026_  
**Route**: Accelerating Equitable Evacuations

**Team Members**:  
- Shruti Kulkarni (GitHub: [@skulkarni3](https://github.com/skulkarni3))  
- Aditi Namboodiripad (GitHub: [@AditiNamboodirirpad](https://github.com/AditiNamboodirirpad)) 
- Lynn Tong (GitHub: [@lintyfresh](https://github.com/lintyfresh)) 
- Chelyah Miller (GitHub: [@cztm](https://github.com/cztm))
- Helen Lin (GitHub: [@HelenLLin](https://github.com/HelenLLin))

---

## Dataset Overview

Summarize the datasets you used and how you processed them.

- Watch Duty Data : Loaded to GCP Bucket and transferred to BigQuery. Joins were used to connect tables that are relevant. This includes evacuation zone, geo event, and fire perimeter data. 
- National Oceanic & Atmospheric Administration (NOAA) High Resolution Rapid Refresh (HRRR): hourly surface wind gust, 2-meter temperature, dewpoint, soil moisture, and snow water equivalent at ~3 km resolution. Fetched hourly and stored in BigQuery
- OverPass: pharmacies, groceries, shelters, schools, fairgrounds, and hotels are queried on-demand from the OverPass API.
- User GPS coordinates: captured at session start and reverse-geocoded from the user's mobile phone in Cloud SQL.
- User Information: household and language information during the onboarding and stored in Cloud SQL
- Chat Messages: system, user and agent messages are stored in Qdrant vector DB for semantic search and
---

## Approach

At session start, the user's GPS coordinates are reverse-geocoded and the Haversine distance to the nearest active WatchDuty fire perimeter is computed. This danger score is wind-adjusted using a Hourly Wildfire Potential (HWP) index derived from HRRR fields and spatially smoothed over a ~27 km neighborhood. A scikit-learn classification model then assigns one of four danger bins (LOW, MEDIUM, HIGH, CRITICAL) based on distance, HWP score, and the user's location danger history. For routing, the user's GPS and WatchDuty fire polygons are passed to OpenRouteService (ORS), which generates a GeoJSON route avoiding all active fire perimeters; users may add waypoints such as pharmacies, or designate zones to avoid. The AI agent receives a structured prompt as a system message containing the user's location, danger bin, evacuation zone status, route, and household profile. It auto-detects language, adjusts tone to danger severity, and generates a personalized evacuation checklist. Conversation history is stored in Qdrant vector DB, enabling semantic search and coherent multi-turn message chains across sessions.

Tools used: 
- Backend : Python (FastAPI, Scikitlearn, SQLAlchemy ), Anthropic API, OpenAI API, GCP APIs, Docker => Deployed to GCP CloudRun
- Frontend : Swift with library dependencies including MapBox and Firebase.
- Database : GCP BigQuery, GCP  CloudSQL, Qdrant (VectorDB)

---

## Results

Data Refresh Model:

Because we only had time series data, the model wasn't highly accurate across all four tiers. However, it performed well at the most important task: distinguishing **Safe vs. non-Safe** HWP conditions over the next 12 hours. That binary signal was enough to meaningfully reduce compute — non-safe zones refresh every hour, safe zones refresh every 3 hours.

**BigQuery ML.EVALUATE results (production model):**

| Metric    | Value |
|-----------|-------|
| Precision | 0.55  |
| Recall    | 0.57  |
| Accuracy  | 0.55  |
| F1 Score  | 0.55  |
| Log Loss  | 0.97  |
| ROC AUC   | 0.82  |

The ROC AUC of 0.82 shows the model is genuinely able to separate classes, even if overall accuracy is modest.

**BigQuery Confusion Matrix:**

| Expected \ Predicted | Elevated  | Extreme   | High      | Safe      |
|----------------------|-----------|-----------|-----------|-----------|
| Elevated             | 1,558,340 | 134,960   | 528,353   | 933,414   |
| Extreme              | 235,314   | 1,040,721 | 400,083   | 33,428    |
| High                 | 1,370,616 | 808,301   | 1,744,941 | 357,034   |
| Safe                 | 624,580   | 98,184    | 143,415   | 2,667,510 |

* The Safe class is predicted most reliably — very few Safe instances are misclassified as Extreme (98k out of ~3.5M)
* Extreme is also well-separated from Safe, which is the critical safety boundary
* Elevated and High are frequently confused with each other, which is acceptable since both trigger the 1-hour refresh cadence

App:

In our testing of the app we found that users could sign up, chat with the agent, and have a customized fire evacuation route ready in less than **3 minutes**. 

---

## Team Contributions

| Name         | Contributions                                                |
|--------------|--------------------------------------------------------------|
| Shruti       | App development, agent creation, EDA, write-up, GitHub setup |
| Chelyah      | Slides, presentation prep, write-up, agent creation          |
| Helen        | Agent creation, poster                                       |
| Aditi        | Agent creation, README, testing                              |
| Lynn         | Slides, presentation prep, data refresh modeling, README     |

---

## How to Reproduce

To get started, clone the repository.
```
git clone https://github.com/skulkarni3/wildfire-exits
```

This project has two directories. 
In order to run the projects, please follow the following steps.

1. app : FastAPI backend server 
    * To run it locally, ensure you have a docker installed.
    ```
    # Build locally
    cd wildfire-exits/app
    docker build -t beacon-api .

    # Run locally
    docker run -v path_to_local_google_application_credentials:/secrets/key.json -e GOOGLE_APPLICATION_CREDENTIALS=/secrets/key.json -p 8080:8080 --env-file .env beacon-api
    ```
    * To deploy on Google Cloud Platform (GCP),
        - Make sure that you have your GCP set up
        - First install, [Google Cloud CLI](https://docs.cloud.google.com/sdk/docs/install-sdk)
        - If it is your first time to use GCP CLI,
        ```
        gcloud auth login
        ```
        Then, deploy to your Google Cloud Run via
        ```
        gcloud run deploy beacon-api \
        --source . \
        --region gcp_region \
        --allow-unauthenticated
        --project project_name
        ```
        - To add environment variables, you can add those on Cloud Run manually or create .env.yaml in a format of .yaml (Ex. ANTHROPIC_API_KEY: value, etc.) and add --env-vars-file .env.yaml
<b>Note:</b> See .env.template and create your .env file with valid values.

2. mobile_gps_app: iOS frontend application
TODO : Shruti Add Steps (try with someone new)
    * Ensure you download Xcode if you want to reproduce the application 
    - On the project - Right Click >> Add Package Dependencies
        - Add the following and ensure to have a dependency to the application.
        1. https://github.com/firebase/firebase-ios-sdk
        2. https://github.com/mapbox/mapbox-navigation-ios.git
<b> Note: </b> On the setting, ensure to change the URL and other parameters accordingly. For Docker, we're using 8080 as a port.

---

## Questions?

Visit the community hub: [WiDS Community](https://community.widsworldwide.org)

