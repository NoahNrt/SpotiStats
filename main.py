import os
import sys

from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

load_dotenv()

bmth_urn = 'spotify:artist:1Ffb6ejR6Fe5IamqA5oRUF' # Always 21 Characters long
sp = spotipy.Spotify(client_credentials_manager=SpotifyClientCredentials(
    client_id=os.getenv("SPOTIFY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
))

results = sp.artist_albums(bmth_urn, album_type='album', limit=10)
albums = results['items']
while results['next']:
    results = sp.next(results)
    albums.extend(results['items'])

for album in albums:
    print(album['name'])