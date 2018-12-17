# -*- coding: utf-8-sig -*-

import googlemaps
import math
import numpy as np
from sklearn.cluster import KMeans

'''
docs:
1. Google Maps Documentation: https://googlemaps.github.io/google-maps-services-python/docs/
2. sklearn kmeans: https://scikit-learn.org/stable/modules/generated/sklearn.cluster.KMeans.html#sklearn.cluster.KMeans
3. KMeans clustering example: https://stackabuse.com/k-means-clustering-with-scikit-learn/
'''

class RouteClustering:
    # cls var
    gm = googlemaps.Client(key='AIzaSyDOa6NIT66QT4zO239JqSR5azRvUaaa4vI')  # initiate google maps related services

    def has_hk_island(self, hk_locations):
        """
        There must be points in NT and KL but not necessarily in HK Island. 
        Therefore we need to check if there is any hk island points.
        """  
        return True if len(hk_locations) > 0 else False

    def get_geocode(self, locations):
        """
        Each point in can be represented in coordinates (longitude and latitude), which is required for K-means clustering.
        This coordinate is called geocode in Google api. This api returns a nested dictionary in a list and step is needed to
        extract useful infomation.

        As this data will be saved to the Database, this function is kept in case once needed and has no practical usage now.
        """
        coordinates = []
        gm = googlemaps.Client(key='AIzaSyDOa6NIT66QT4zO239JqSR5azRvUaaa4vI')  # initiate google maps related services
        for address in locations:
            data = gm.geocode(address)
            if len(data) == 0:
                return
            data = data[0]['geometry']['location']
            coordinates.append([data['lng'], data['lat']])

        return coordinates

    def geo_address_dict(self, geo_list, address_list):
        """
        As the K-means clustering is done by using geocode, a reference dictionary between geocode and address is needed 
        to return a route list in address for Google direction api and final result.

        This function is no longer required as the data is given along with the addresses from the database.
        """
        ga_dict = {}
        for i in range(len(geo_list)):
            ga_dict[tuple(geo_list[i])] = address_list[i] # lists are mutable and unable to be used as keys

        return ga_dict

    def kmeans_cluster(self, ntkl_geo_list, hk_geo_list=[]):
        """
        Priliminary clustering to give 3 clusters (routes). These routes are formed base on K-Means and can be imbalance in
        terms of number of points, work time and drive distance.
        """
        ntkl_np = np.array(ntkl_geo_list)  # only numpy array can be used for KMeans functions
        if not hk_geo_list == []:
            ntkl_kmeans = KMeans(n_clusters=2) # define number of clusters 
            ntkl_kmeans.fit(ntkl_np) # this function performs kmeans clustering
            
            # With only one cluster in HK Island, all points belong to it and the origin coordinates is the most important info.
            hk_centre = KMeans(n_clusters=1).fit(np.array(hk_geo_list)).cluster_centers_.tolist()[0]
            # write HK data into the dictionary first. It's key is 99 to indicate HK island route
            cluster_result = { 99: { 'origin': hk_centre, 'points': hk_geo_list } }  
        else:
            ntkl_kmeans = KMeans(n_clusters=3) # there will be 3 clusters if there is no points in HK Island
            ntkl_kmeans.fit(ntkl_np)
            cluster_result = {}
        
        labels = ntkl_kmeans.labels_.tolist() # a list of cluster index assigned to the points
        ntkl_centres = ntkl_kmeans.cluster_centers_.tolist()  # the coordinates of the cluster centres
        origin_index = 0

        for i in range(len(ntkl_geo_list)):
            if not labels[i] in cluster_result:
                cluster_result[labels[i]] = {
                                                'origin': ntkl_centres[origin_index],
                                                'points': [ntkl_geo_list[i]]
                                            }
                origin_index += 1
            else:
                cluster_result[labels[i]]['points'].append(ntkl_geo_list[i])

        return cluster_result

    def get_value(self, string): 
        """
        This is to get of numeric section of the required data  
        """
        string = string.split(' ')[0]
        try:
            value = float(string)
            return value
        except ValueError:
            print('String with unexpected format given')
            return

    def get_work_info(self, coordinates, address_dict):
        """
        This function intakes a list of coordinates and get driving time from Google Directions API.The API also returns a route
        with optimized waypoints (the AI part). The returned work_info includes working time, optimized route and route distance.
        """
        info = {}
        waypoints = [] # for google direction api
        locations = [] # for result
        # convert the goecode to address for using direction function
        for coor in coordinates:
            waypoints.append(address_dict[tuple(coor)])
        
        # Every driver will start and stop at company as assumed
        company = '17-19 Dai Hei Street, Tai Po Industrial Estate, Tai Po, New Territories, HK'
        
        data = gm.directions(
            origin=company,
            destination=company,
            mode='driving',
            waypoints=waypoints,
            optimize_waypoints=True,
            language='zh-HK')

        for key in data[0]['legs']:  
            duration = key['duration']['text']
            distance = key['distance']['text']
            if '分' in duration:
                time = self.get_value(duration) 
                
            elif '小時' in duration:
                time = self.get_value(duration) * 60 

            if '公里' in distance:
                distance = self.get_value(distance)
            elif '公尺' in distance:
                distance = self.get_value(distance) / 1000
             
            # add up the values for distance (km) and duration (min)
            info['duration'] = round(info.get('duration', 0) + time, 1)
            info['distance'] = round(info.get('distance', 0) + distance, 1)

        for i in data[0]['waypoint_order']:
            locations.append(waypoints[i])  # get the route sequence by using the waypoints index sequence
        
        driving_time  = info['duration']
        route_distance = info['distance']

        uniq_add = len(set(waypoints))  # number of unique address
        repeat_add = len(waypoints) - uniq_add  # number of repeated address 
        del_time = uniq_add*20 + repeat_add*5  # each address needs 20 min delivery time and each repeated address needs 5 extra min
        
        work_info = {}
        work_info['duration'] = driving_time + del_time
        work_info['route'] = locations
        work_info['distance'] = route_distance
        
        return work_info 


    def is_balanced(self, work_time):
        """
        Route balance check based in total working time (driving time + delivery time). If time difference is more than 90 min, the points
        have to be re-assigned. Time difference can be changed by either addition or substraction depending on users' needs.
        But criteria less than 35 min may probably lead the script into infinite loop; more than 120 min may left the script useless.
        """
        time = list(work_time.values())
        return True if max(time) - min(time) >= 90 else False 

    def rearrange_routes(self, work_time, cluster_result):
        """
        Each point of the longest route will be compared with the shortest route origin. Point that is closest to the origin will be 
        transfered.
        """

        longest = max(work_time, key=work_time.get)  
        shortest = min(work_time, key=work_time.get)
        short_origin = cluster_result[shortest]['origin']
        
        distance_list = []  # store all distance between the points in longest route and the shortest origin 
        for point in cluster_result[longest]['points']:
            distance = math.sqrt((point[0]-short_origin[0])**2 + (point[1]-short_origin[1])**2) # sqrt((x1-x2)^2 + (y1-y2)^2)
            distance_list.append(distance)

        # pick the point from the longest route and give to the shortest
        # It is possible
        point_to_share = cluster_result[longest]['points'][distance_list.index(min(distance_list))]
        while point_to_share in cluster_result[longest]['points']:
            cluster_result[longest]['points'].remove(point_to_share)
            cluster_result[shortest]['points'].append(point_to_share)

        return cluster_result