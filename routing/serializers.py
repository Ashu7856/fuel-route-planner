from rest_framework import serializers


class TripRequestSerializer(serializers.Serializer):
    start = serializers.CharField(help_text='"City, ST", "lat,lng" or a US address')
    finish = serializers.CharField(help_text='"City, ST", "lat,lng" or a US address')
    range_miles = serializers.FloatField(required=False, default=500, min_value=50, max_value=2000)
    mpg = serializers.FloatField(required=False, default=10, min_value=1, max_value=100)
    corridor_miles = serializers.FloatField(required=False, default=10, min_value=1, max_value=50)
    initial_fuel_miles = serializers.FloatField(required=False, default=None, min_value=0)
