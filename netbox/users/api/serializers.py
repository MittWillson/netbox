from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from netbox.api.fields import ContentTypeField, IPNetworkSerializer, SerializedPKRelatedField
from netbox.api.serializers import ValidatedModelSerializer
from users.models import ObjectPermission, Token
from .nested_serializers import *


__all__ = (
    'GroupSerializer',
    'ObjectPermissionSerializer',
    'TokenSerializer',
    'UserSerializer',
)


class UserSerializer(ValidatedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name='users-api:user-detail')
    groups = SerializedPKRelatedField(
        queryset=Group.objects.all(),
        serializer=NestedGroupSerializer,
        required=False,
        many=True
    )

    class Meta:
        model = get_user_model()
        fields = (
            'id', 'url', 'display', 'username', 'password', 'first_name', 'last_name', 'email', 'is_staff', 'is_active',
            'date_joined', 'groups',
        )
        extra_kwargs = {
            'password': {'write_only': True}
        }

    def create(self, validated_data):
        """
        Extract the password from validated data and set it separately to ensure proper hash generation.
        """
        password = validated_data.pop('password')
        user = super().create(validated_data)
        user.set_password(password)
        user.save()

        return user

    @extend_schema_field(OpenApiTypes.STR)
    def get_display(self, obj):
        if full_name := obj.get_full_name():
            return f"{obj.username} ({full_name})"
        return obj.username


class GroupSerializer(ValidatedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name='users-api:group-detail')
    user_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Group
        fields = ('id', 'url', 'display', 'name', 'user_count')


class TokenSerializer(ValidatedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name='users-api:token-detail')
    key = serializers.CharField(
        min_length=40,
        max_length=40,
        allow_blank=True,
        required=False,
        write_only=not settings.ALLOW_TOKEN_RETRIEVAL
    )
    user = NestedUserSerializer()
    allowed_ips = serializers.ListField(
        child=IPNetworkSerializer(),
        required=False,
        allow_empty=True,
        default=[]
    )

    class Meta:
        model = Token
        fields = (
            'id', 'url', 'display', 'user', 'created', 'expires', 'last_used', 'key', 'write_enabled', 'description',
            'allowed_ips',
        )

    def to_internal_value(self, data):
        if 'key' not in data:
            data['key'] = Token.generate_key()
        return super().to_internal_value(data)

    def validate(self, data):

        # If the Token is being created on behalf of another user, enforce the grant_token permission.
        request = self.context.get('request')
        token_user = data.get('user')
        if token_user and token_user != request.user and not request.user.has_perm('users.grant_token'):
            raise PermissionDenied("This user does not have permission to create tokens for other users.")

        return super().validate(data)


class TokenProvisionSerializer(TokenSerializer):
    user = NestedUserSerializer(
        read_only=True
    )
    username = serializers.CharField(
        write_only=True
    )
    password = serializers.CharField(
        write_only=True
    )
    last_used = serializers.DateTimeField(
        read_only=True
    )
    key = serializers.CharField(
        read_only=True
    )

    class Meta:
        model = Token
        fields = (
            'id', 'url', 'display', 'user', 'created', 'expires', 'last_used', 'key', 'write_enabled', 'description',
            'allowed_ips', 'username', 'password',
        )

    def validate(self, data):
        # Validate the username and password
        username = data.pop('username')
        password = data.pop('password')
        user = authenticate(request=self.context.get('request'), username=username, password=password)
        if user is None:
            raise AuthenticationFailed("Invalid username/password")

        # Inject the user into the validated data
        data['user'] = user

        return data


class ObjectPermissionSerializer(ValidatedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name='users-api:objectpermission-detail')
    object_types = ContentTypeField(
        queryset=ContentType.objects.all(),
        many=True
    )
    groups = SerializedPKRelatedField(
        queryset=Group.objects.all(),
        serializer=NestedGroupSerializer,
        required=False,
        many=True
    )
    users = SerializedPKRelatedField(
        queryset=get_user_model().objects.all(),
        serializer=NestedUserSerializer,
        required=False,
        many=True
    )

    class Meta:
        model = ObjectPermission
        fields = (
            'id', 'url', 'display', 'name', 'description', 'enabled', 'object_types', 'groups', 'users', 'actions',
            'constraints',
        )
