from rest_framework.views import APIView
from rest_framework import generics
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from .models import *
from .serializers import *


class OrganizationAPIView(generics.CreateAPIView):
        queryset = Organization.objects.all()
        serializer_class = OrganizationSerializer
        permission_classes = [IsAuthenticated]

        def get(self, request):
            queryset = self.get_queryset()
            serializers = OrganizationSerializer(queryset, many=True)
            return Response(serializers.data)

        def post(self, request):
              serializers = OrganizationSerializer(data=request.data)
              if serializers.is_valid():
                serializers.save()
                return Response(serializers.data, status=status.HTTP_201_CREATED)
              return Response(serializers.errors, status=status.HTTP_400_BAD_REQUEST)

class OrganizationRoleAPIView(generics.CreateAPIView):
        queryset = OrganizationRole.objects.all()
        serializer_class = OrganizationRoleSerializer
        # permission_classes = [IsAuthenticated]

        def get(self, request):
            queryset = self.get_queryset()
            serializers = OrganizationRoleSerializer(queryset, many=True)
            return Response(serializers.data)

        def post(self, request):
              serializers = OrganizationRoleSerializer(data=request.data)
              if serializers.is_valid():
                serializers.save()
                return Response(serializers.data, status=status.HTTP_201_CREATED)
              return Response(serializers.errors, status=status.HTTP_400_BAD_REQUEST)
