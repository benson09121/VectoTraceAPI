from rest_framework.views import APIView
from rest_framework import generics
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from .models import *
from .serializers import *
from .permissions import IsOrgMember


class OrganizationAPIView(generics.CreateAPIView):

        def get_permissions(self):
             if self.request.method == "GET":
                  permission_classes = [IsAuthenticated, IsOrgMember]
            
             elif self.request.method == "POST":
                  permission_classes = [IsAuthenticated]
            
             return [permission() for permission in permission_classes]
    
        def get(self, request):
            user = request.user
            queryset = Organization.objects.filter(organizationmember__users=user)
            serializers = OrganizationCreateSerializer(queryset, many=True)
            return Response(serializers.data)

        def create(self, request):
              serializers = OrganizationCreateSerializer(data=request.data, context={'request': request})
              if serializers.is_valid():
                serializers.save()
                return Response(serializers.data, status=status.HTTP_201_CREATED)
              return Response(serializers.errors, status=status.HTTP_400_BAD_REQUEST)

class OrganizationRoleAPIView(generics.CreateAPIView):
        queryset = OrganizationRole.objects.all()
        serializer_class = OrganizationRoleSerializer
        permission_classes = [IsAuthenticated]

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
