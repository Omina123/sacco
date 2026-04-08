import folium  
m =folium.Map(location=[20.5931,78.9629],zoom_start=4)
folium.Marker(
    location=[36.7809,77.2090],
    popup="new delhi",
    tooltip='Capital of India').add_to(m)
m.save("om.html")