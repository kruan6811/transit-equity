import requests
import pandas as pd
import numpy as np
from io import StringIO, BytesIO
import json
import os
from lib import *


stops2ridership = {
    'VineyardRTA': "Woods Hole, Martha's Vineyard and Nantucket Steamship Authority",
    'CapeCodRTA': "Cape Cod Regional Transit Authority",
    'LowellRTA': 'Lowell Regional Transit Authority',
    'CapeAnnRTA': "Cape Ann Transportation Authority",
    'BerkshireRTA': "Berkshire Regional Transit Authority",
    'MontachusettRTA': "Montachusett Regional Transit Authority",
    'MerrimackValleyRTA': "Merrimack Valley Regional Transit Authority",
    'PioneerValleyRTA': 'Pioneer Valley Transit Authority',
    'MetroWestRTA': 'MetroWest Regional Transit Authority',
    'WRTA': 'Worcester Regional Transit Authority COA',
    'BrocktonAreaRTA': 'Brockton Area Transit Authority'
}


def get_bus_stop_data() -> pd.DataFrame:
    """Get MA data for RTA bus stops"""
    RTA_STOPS_URL = 'https://gis.massdot.state.ma.us/arcgis/rest/services/Multimodal/RTAs/FeatureServer/1/query?where=1%3D1&outFields=*&outSR=4326&f=json'
    RTA_STOPS_DATA = requests.get(RTA_STOPS_URL)
    stops_data = json.loads(RTA_STOPS_DATA.content)['features']
    return bus_stops_median_household_income(stops_data)


def get_route_data() -> pd.DataFrame:
    """Get route data for RTA's"""
    RTA_ROUTE_URL = 'https://opendata.arcgis.com/datasets/1cb5c63d6f114f8a94c6d5a0e03ae62e_0.csv?outSR=%7B%22latestWkid%22%3A3857%2C%22wkid%22%3A102100%7D'
    RTA_ROUTE_DATA = requests.get(RTA_ROUTE_URL)
    return pd.read_csv(StringIO(RTA_ROUTE_DATA.content.decode()))


def get_ridership_data() -> pd.DataFrame:
    """Get ridership data for RTA's"""
    RTA_RIDERSHIP_URL = 'https://www.transit.dot.gov/sites/fta.dot.gov/files/2020-10/August%202020%20Adjusted%20Database.xlsx'
    RTA_RIDERSHIP_DATA = requests.get(RTA_RIDERSHIP_URL)
    ridership_df = pd.read_excel(BytesIO(RTA_RIDERSHIP_DATA.content), sheet_name='MASTER')
    ridership_df = ridership_df[ridership_df.Mode == 'MB'] # only buses
    return ridership_df[ridership_df['HQ State'] == 'MA'] # only buses


def get_tract_population_data() -> pd.DataFrame:
    """Get population data per census tracts"""
    return get_population().drop(columns=['state', 'county'])


def get_county_population_data() -> pd.DataFrame:
    """Get population data per county tract"""
    population_data = np.array(requests.get(
        "https://api.census.gov/data/2018/pep/population?get=COUNTY,DATE_CODE,DATE_DESC,DENSITY,POP,GEONAME,STATE&for=county:*&in=state:25"
    ).json())
    population_headers = population_data[0].tolist()
    population_data =  population_data[1:]
    county_population_df = pd.DataFrame(
        {header: population_data[:, population_headers.index(header)] for header in population_headers}
    ).drop(columns=['state', 'county'])
    return county_population_df.loc[county_population_df['DATE_DESC'] == '7/1/2018 population estimate']


def map_stops_to_routes():
    """Add stops to routes"""
	# Filepath
	bus_routes_fp = "../RTA_Bus_Routes-shp/RTA_Bus_Routes.shp"
	bus_stops_fp = "../RTA_Bus_Stops-shp/RTA_Bus_Stops.shp"

	# Read the data
	bus_routes_df = gpd.read_file(bus_routes_fp)
	bus_stops_df = gpd.read_file(bus_stops_fp)

	# Pick specific columns
	routes = bus_routes_df[['OBJECTID','geometry','route_id', 'route_shor', 'route_long']]
	stops = bus_stops_df[['OBJECTID','geometry','stop_id']]

	# map bus stops to routes
	mapped_routes = [-1] * len(stops)

	for index, row in routes.iterrows():
	    line = row['geometry']
	    for index2, row2 in stops.iterrows():
	        stop = row2['geometry']

	        if line.distance(stop) < 100:
	            mapped_routes[index2] = row['route_id']

	stops['route_id'] = mapped_routes
    stops.to_csv('../data/bus_stop_route_mapping.csv')
	return stops # stops.to_csv('../data/bus_stop_route_mapping.csv')


def get_joined_data():
    """Returns bus stop area household income data attached with bus routes"""
    income = pd.read_csv('../data/bus_area_income_ma.csv', index_col=0).drop(columns=['route'])
    stop_route_map = pd.read_csv('../data/bus_stop_route_mapping.csv', index_col=0)
    result = pd.merge(income, stop_route_map, on='stop_id', how='inner')
    result.to_csv('../data/result.csv') 
    return result


def generate():
    """Generates all datasets concurrently"""
    if not os.path.exists('../data'):
        raise Exception('Missing ../data/bus_area_income.csv xor ../data/tl_2019_25_tract.shp')

    route_df = get_route_data()
    route_df = route_df.drop(columns=['route_desc', 'route_color', 'route_text_color', 'route_sort_order', 'min_headway_minutes', 'eligibility_restricted', 'continuous_pickup', 'continuous_drop_off', 'route_type_text'])
    
    population_df = get_tract_population_data()

    ridership_df = get_ridership_data()
    ridership_df = ridership_df[['5 digit NTD ID', 'Agency', 'Service Area Population', 'TOS', 'Active', 'Passenger Miles FY', 'Unlinked Passenger Trips FY', 'Fares FY', 'Operating Expenses FY', 'Average Cost per Trip FY', 'Average Fares per Trip FY']]

    county_df = get_county_population_data()

    # join population_df to bus_area_income_df
    bus_area_income_df = get_bus_stop_data()
    bus_area_income_df = pd.merge(bus_area_income_df, population_df, how='inner', left_on='census_tract', right_on='tract')
    # drop negative income data
    bus_area_income_df['median_household_income'] = bus_area_income_df['median_household_income'].astype(float)
    bus_area_income_df = bus_area_income_df[bus_area_income_df.median_household_income > 0] 
    bus_area_income_df.dropna()
    # rename population column
    bus_area_income_df = bus_area_income_df.rename(columns={"B00001_001E": "population"})
    # drop duplicate bus stops
    bus_area_income_df = bus_area_income_df.drop_duplicates(subset=['stop_id'])
    # drop unnecessary columns
    bus_area_income_df = bus_area_income_df.drop(columns=['platform_code', 'zone_id', 'stop_timezone', 'position', 'direction', 'state', 'stop_desc'])

    # TODO: Verify this has all the MA rta's
    ma_riders = ridership_df.loc[ridership_df['UZA Name'].str.contains(', MA')]
    ma_riders = ma_riders.loc[ma_riders['Agency'] != 'Massachusetts Bay Transportation Authority']
    agency_set = list(set([stop['attributes']['Agency'] for stop in stops_data]))

    bus_area_income_df.to_csv('../data/bus_area_income_ma.csv')
    route_df.to_csv('../data/rta_route_ma.csv')
    ridership_df.to_csv('../data/rta_ridership_ma.csv')
    
    return {
        "route_df": route_df,
        "population_df": population_df,
        "ridership_df": ridership_df,
        "county_df": county_df,
        "bus_area_income": bus_area_income_df,
        "ma_riders": ma_riders,
        "result": get_joined_data()
    }