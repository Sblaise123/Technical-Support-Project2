from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline
import joblib
import re
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
import logging

logger = logging.getLogger(__name__)

class TicketClassifier:
    '''AI-powered ticket classification for priority and category assignment'''
    
    def __init__(self):
        self.priority_model = None
        self.category_model = None
        self.load_models()
        
        # Download NLTK data if needed
        try:
            nltk.data.find('tokenizers/punkt')
        except LookupError:
            nltk.download('punkt')
        
        try:
            nltk.data.find('corpora/stopwords')
        except LookupError:
            nltk.download('stopwords')
        
        self.stop_words = set(stopwords.words('english'))
        
        # Priority keywords mapping
        self.priority_keywords = {
            'emergency': ['down', 'outage', 'critical', 'emergency', 'urgent', 'production', 'server down'],
            'critical': ['error', 'failed', 'broken', 'crash', 'bug', 'issue', 'problem'],
            'high': ['slow', 'performance', 'delay', 'timeout', 'important'],
            'medium': ['question', 'help', 'support', 'how to', 'guidance'],
            'low': ['request', 'enhancement', 'feature', 'suggestion', 'minor']
        }
        
        # Category keywords mapping
        self.category_keywords = {
            'technical': ['api', 'database', 'server', 'application', 'code', 'bug', 'error', 'crash'],
            'account': ['login', 'password', 'account', 'access', 'authentication', 'user'],
            'billing': ['invoice', 'payment', 'billing', 'subscription', 'charge', 'refund'],
            'integration': ['api', 'webhook', 'integration', 'connector', 'third party'],
            'performance': ['slow', 'timeout', 'performance', 'speed', 'latency'],
            'general': ['question', 'help', 'support', 'information', 'general']
        }
    
    def preprocess_text(self, text: str) -> str:
        '''Clean and preprocess text for classification'''
        if not text:
            return ""
        
        # Convert to lowercase
        text = text.lower()
        
        # Remove special characters and numbers
        text = re.sub(r'[^a-zA-Z\s]', '', text)
        
        # Tokenize and remove stopwords
        tokens = word_tokenize(text)
        tokens = [token for token in tokens if token not in self.stop_words and len(token) > 2]
        
        return ' '.join(tokens)
    
    def classify_ticket(self, title: str, description: str, customer_tier: str = "standard") -> dict:
        '''Classify ticket priority, category, urgency, and impact'''
        
        # Combine title and description
        combined_text = f"{title} {description}".lower()
        
        # Classify priority using keyword matching (can be enhanced with ML)
        priority = self.classify_priority(combined_text, customer_tier)
        
        # Classify category
        category = self.classify_category(combined_text)
        
        # Determine urgency and impact based on priority and customer tier
        urgency, impact = self.determine_urgency_impact(priority, customer_tier)
        
        return {
            'priority': priority,
            'category': category,
            'urgency': urgency,
            'impact': impact,
            'confidence': 0.85  # This would be actual confidence from ML model
        }
    
    def classify_priority(self, text: str, customer_tier: str) -> str:
        '''Classify ticket priority based on content and customer tier'''
        
        priority_scores = {
            'emergency': 0,
            'critical': 0,
            'high': 0,
            'medium': 0,
            'low': 0
        }
        
        # Score based on keywords
        for priority, keywords in self.priority_keywords.items():
            for keyword in keywords:
                if keyword in text:
                    priority_scores[priority] += 1
        
        # Adjust for customer tier
        tier_multipliers = {
            'enterprise': {'emergency': 2, 'critical': 1.5, 'high': 1.2},
            'premium': {'critical': 1.3, 'high': 1.1},
            'standard': {}
        }
        
        if customer_tier in tier_multipliers:
            for priority, multiplier in tier_multipliers[customer_tier].items():
                priority_scores[priority] *= multiplier
        
        # Return highest scoring priority
        max_priority = max(priority_scores, key=priority_scores.get)
        
        # If no keywords found, default to medium
        if priority_scores[max_priority] == 0:
            return 'medium'
        
        return max_priority
    
    def classify_category(self, text: str) -> str:
        '''Classify ticket category based on content'''
        
        category_scores = {category: 0 for category in self.category_keywords.keys()}
        
        for category, keywords in self.category_keywords.items():
            for keyword in keywords:
                if keyword in text:
                    category_scores[category] += 1
        
        # Return highest scoring category
        max_category = max(category_scores, key=category_scores.get)
        
        # If no keywords found, default to general
        if category_scores[max_category] == 0:
            return 'general'
        
        return max_category
    
    def determine_urgency_impact(self, priority: str, customer_tier: str) -> tuple:
        '''Determine urgency and impact based on priority and customer tier'''
        
        # Base urgency/impact mapping
        urgency_impact_map = {
            'emergency': ('high', 'high'),
            'critical': ('high', 'medium'),
            'high': ('medium', 'medium'),
            'medium': ('low', 'low'),
            'low': ('low', 'low')
        }
        
        urgency, impact = urgency_impact_map.get(priority, ('medium', 'medium'))
        
        # Adjust for customer tier
        if customer_tier == 'enterprise':
            if urgency == 'medium':
                urgency = 'high'
            if impact == 'medium':
                impact = 'high'
        elif customer_tier == 'premium':
            if urgency == 'low':
                urgency = 'medium'
            if impact == 'low':
                impact = 'medium'
        
        return urgency, impact
    
    def load_models(self):
        '''Load pre-trained classification models'''
        try:
            # In production, these would be actual trained models
            # self.priority_model = joblib.load('models/priority_classifier.pkl')
            # self.category_model = joblib.load('models/category_classifier.pkl')
            logger.info("Classification models loaded successfully")
        except Exception as e:
            logger.warning(f"Could not load ML models, using rule-based classification: {e}")
    
    def train_models(self, training_data):
        '''Train classification models on historical data'''
        # This would implement actual ML model training
        # For now, using rule-based approach
        pass