from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status
from base.models import College, Confession

User = get_user_model()


class ConfessionModelTestCase(TestCase):
    """Test cases for the Confession model."""
    
    def setUp(self):
        self.college = College.objects.create(
            name="Test University",
            domain="test.edu",
            window_start="20:00:00",
            window_end="21:00:00",
            is_active=True
        )
        self.user = User.objects.create_user(
            username="testuser",
            email="test@test.edu",
            password="testpass123",
            college=self.college
        )
        
    def test_confession_creation(self):
        """Test creating a confession."""
        confession = Confession.objects.create(
            content="This is a test confession",
            author=self.user,
            college=self.college
        )
        
        self.assertEqual(confession.content, "This is a test confession")
        self.assertEqual(confession.author, self.user)
        self.assertEqual(confession.college, self.college)
        self.assertEqual(confession.likes_count, 0)
        self.assertEqual(confession.dislikes_count, 0)
        
    def test_confession_likes_dislikes(self):
        """Test likes and dislikes functionality."""
        user2 = User.objects.create_user(
            username="testuser2",
            email="test2@test.edu",
            password="testpass123",
            college=self.college
        )
        
        confession = Confession.objects.create(
            content="Test confession for likes",
            author=self.user,
            college=self.college
        )
        
        # Test likes
        confession.liked_by.add(user2)
        self.assertEqual(confession.likes_count, 1)
        
        # Test dislikes
        confession.disliked_by.add(user2)
        self.assertEqual(confession.dislikes_count, 1)
        
        # User should be in both lists
        self.assertIn(user2, confession.liked_by.all())
        self.assertIn(user2, confession.disliked_by.all())


class ConfessionAPITestCase(APITestCase):
    """Test cases for confession API endpoints."""
    
    def setUp(self):
        self.college = College.objects.create(
            name="Test University",
            domain="test.edu",
            window_start="20:00:00",
            window_end="21:00:00",
            is_active=True
        )
        self.user = User.objects.create_user(
            username="testuser",
            email="test@test.edu",
            password="testpass123",
            college=self.college
        )
        self.other_college = College.objects.create(
            name="Other University",
            domain="other.edu",
            window_start="20:00:00",
            window_end="21:00:00",
            is_active=True
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@other.edu",
            password="testpass123",
            college=self.other_college
        )
        
    def test_create_confession_authenticated(self):
        """Test creating a confession with authenticated user."""
        self.client.force_authenticate(user=self.user)
        
        url = reverse('create_confession')
        data = {'content': 'This is my test confession'}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['content'], 'This is my test confession')
        self.assertTrue(response.data['is_own'])
        self.assertEqual(response.data['likes_count'], 0)
        self.assertEqual(response.data['dislikes_count'], 0)
        
        # Check confession was created in database
        confession = Confession.objects.get(id=response.data['id'])
        self.assertEqual(confession.content, 'This is my test confession')
        self.assertEqual(confession.author, self.user)
        self.assertEqual(confession.college, self.college)
        
    def test_create_confession_unauthenticated(self):
        """Test creating a confession without authentication should fail."""
        url = reverse('create_confession')
        data = {'content': 'This should fail'}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
    def test_create_confession_no_content(self):
        """Test creating a confession without content should fail."""
        self.client.force_authenticate(user=self.user)
        
        url = reverse('create_confession')
        data = {'content': ''}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)
        
    def test_create_confession_too_long(self):
        """Test creating a confession with content too long should fail."""
        self.client.force_authenticate(user=self.user)
        
        url = reverse('create_confession')
        data = {'content': 'x' * 1001}  # 1001 characters, over the 1000 limit
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('too long', response.data['error'])
        
    def test_list_confessions_authenticated(self):
        """Test listing confessions for authenticated user."""
        self.client.force_authenticate(user=self.user)
        
        # Create test confessions
        confession1 = Confession.objects.create(
            content="First confession",
            author=self.user,
            college=self.college
        )
        confession2 = Confession.objects.create(
            content="Second confession",
            author=self.user,
            college=self.college
        )
        # Create confession from other college (should not appear)
        Confession.objects.create(
            content="Other college confession",
            author=self.other_user,
            college=self.other_college
        )
        
        url = reverse('list_confessions')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['confessions']), 2)
        self.assertEqual(response.data['college'], self.college.name)
        self.assertEqual(response.data['total_count'], 2)
        
        # Check confession data structure
        confession_data = response.data['confessions'][0]  # Should be newest first
        self.assertIn('id', confession_data)
        self.assertIn('content', confession_data)
        self.assertIn('created_at', confession_data)
        self.assertIn('likes_count', confession_data)
        self.assertIn('dislikes_count', confession_data)
        self.assertIn('user_liked', confession_data)
        self.assertIn('user_disliked', confession_data)
        self.assertIn('is_own', confession_data)
        
    def test_list_confessions_unauthenticated(self):
        """Test listing confessions without authentication should fail."""
        url = reverse('list_confessions')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
    def test_list_confessions_college_filtering(self):
        """Test that confessions are properly filtered by college."""
        self.client.force_authenticate(user=self.user)
        
        # Create confessions in different colleges
        Confession.objects.create(
            content="My college confession",
            author=self.user,
            college=self.college
        )
        Confession.objects.create(
            content="Other college confession",
            author=self.other_user,
            college=self.other_college
        )
        
        url = reverse('list_confessions')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['confessions']), 1)
        self.assertEqual(response.data['confessions'][0]['content'], "My college confession")
        
    def test_confession_likes_in_response(self):
        """Test that like/dislike information is correctly included in API responses."""
        self.client.force_authenticate(user=self.user)
        
        # Create another user in same college
        user2 = User.objects.create_user(
            username="testuser2",
            email="test2@test.edu",
            password="testpass123",
            college=self.college
        )
        
        confession = Confession.objects.create(
            content="Test confession",
            author=user2,
            college=self.college
        )
        
        # Have the current user like the confession
        confession.liked_by.add(self.user)
        
        url = reverse('list_confessions')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        confession_data = response.data['confessions'][0]
        
        self.assertEqual(confession_data['likes_count'], 1)
        self.assertEqual(confession_data['dislikes_count'], 0)
        self.assertTrue(confession_data['user_liked'])
        self.assertFalse(confession_data['user_disliked'])
        self.assertFalse(confession_data['is_own'])  # Not the current user's confession
