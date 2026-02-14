from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import re
import os

app = Flask(__name__)

# Configure CORS - allow all origins in production (you can restrict this later)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Get port from environment variable (Render sets this)
PORT = int(os.environ.get('PORT', 5000))

def extract_recipe_data(url):
    """
    Fetch and extract recipe data from a URL
    """
    try:
        # Fetch the webpage
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract domain for source
        domain = urlparse(url).netloc.replace('www.', '')
        source = domain.split('.')[0].capitalize()
        
        # Try to find recipe data using common patterns
        recipe_data = {
            'url': url,
            'source': source,
            'title': extract_title(soup),
            'description': extract_description(soup),
            'prepTime': extract_time(soup, 'prep'),
            'cookTime': extract_time(soup, 'cook'),
            'totalTime': extract_time(soup, 'total'),
            'servings': extract_servings(soup),
            'ingredients': extract_ingredients(soup),
            'instructions': extract_instructions(soup),
            'imageUrl': extract_image(soup)
        }
        
        # Check if we actually got meaningful data
        has_ingredients = recipe_data['ingredients'] and recipe_data['ingredients'] != ["Ingredients not found"]
        has_instructions = recipe_data['instructions'] and recipe_data['instructions'] != ["Instructions not found"]
        
        if not has_ingredients or not has_instructions:
            # We got the page but couldn't extract recipe data
            raise Exception(
                f"This website is blocking automated access or uses a format we don't support. "
                f"Please use 'Manual Entry' or 'Scan Recipe' to add this recipe!"
            )
        
        return recipe_data
    
    except requests.exceptions.Timeout:
        raise Exception("The website took too long to respond. Please try again or use Manual Entry.")
    
    except requests.exceptions.ConnectionError:
        raise Exception("Could not connect to the website. Check your internet connection or try a different URL.")
    
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            raise Exception(
                "This website is blocking automated access. "
                "Please use 'Manual Entry' or 'Scan Recipe' to add this recipe!"
            )
        elif e.response.status_code == 404:
            raise Exception("Recipe not found at this URL. Please check the link and try again.")
        else:
            raise Exception(f"Website returned error {e.response.status_code}. Please try a different URL.")
    
    except Exception as e:
        # If it's already our custom exception, re-raise it
        if "Manual Entry" in str(e) or "Scan Recipe" in str(e):
            raise
        # Otherwise, generic error
        raise Exception(f"Could not extract recipe from {urlparse(url).netloc}. This site may block scraping or use a format we don't support.")

def extract_title(soup):
    """Extract recipe title"""
    # Try JSON-LD first
    json_ld = soup.find('script', type='application/ld+json')
    if json_ld:
        import json
        try:
            data = json.loads(json_ld.string)
            if isinstance(data, list):
                data = data[0]
            if data.get('@type') == 'Recipe' and data.get('name'):
                return data['name']
        except:
            pass
    
    # Try meta tags
    og_title = soup.find('meta', property='og:title')
    if og_title and og_title.get('content'):
        return og_title['content']
    
    # Try h1
    h1 = soup.find('h1')
    if h1:
        return h1.get_text().strip()
    
    # Fallback to page title
    title = soup.find('title')
    if title:
        return title.get_text().strip()
    
    return "Recipe"

def extract_description(soup):
    """Extract recipe description"""
    # Try JSON-LD
    json_ld = soup.find('script', type='application/ld+json')
    if json_ld:
        import json
        try:
            data = json.loads(json_ld.string)
            if isinstance(data, list):
                data = data[0]
            if data.get('@type') == 'Recipe' and data.get('description'):
                return data['description']
        except:
            pass
    
    # Try meta description
    meta_desc = soup.find('meta', {'name': 'description'})
    if meta_desc and meta_desc.get('content'):
        return meta_desc['content']
    
    og_desc = soup.find('meta', property='og:description')
    if og_desc and og_desc.get('content'):
        return og_desc['content']
    
    return ""

def extract_time(soup, time_type):
    """Extract prep/cook/total time"""
    # Try JSON-LD
    json_ld = soup.find('script', type='application/ld+json')
    if json_ld:
        import json
        try:
            data = json.loads(json_ld.string)
            if isinstance(data, list):
                data = data[0]
            if data.get('@type') == 'Recipe':
                if time_type == 'prep' and data.get('prepTime'):
                    return parse_iso_duration(data['prepTime'])
                elif time_type == 'cook' and data.get('cookTime'):
                    return parse_iso_duration(data['cookTime'])
                elif time_type == 'total' and data.get('totalTime'):
                    return parse_iso_duration(data['totalTime'])
        except:
            pass
    
    # Try to find in HTML
    patterns = {
        'prep': [r'prep(?:aration)?\s*time[:\s]*([0-9]+\s*(?:hour|hr|min|minute)s?)', 'prep-time', 'preptime'],
        'cook': [r'cook(?:ing)?\s*time[:\s]*([0-9]+\s*(?:hour|hr|min|minute)s?)', 'cook-time', 'cooktime'],
        'total': [r'total\s*time[:\s]*([0-9]+\s*(?:hour|hr|min|minute)s?)', 'total-time', 'totaltime']
    }
    
    for pattern in patterns.get(time_type, []):
        if isinstance(pattern, str):
            # Try class name
            time_elem = soup.find(class_=re.compile(pattern, re.I))
            if time_elem:
                return time_elem.get_text().strip()
        else:
            # Try regex in text
            text = soup.get_text()
            match = re.search(pattern, text, re.I)
            if match:
                return match.group(1)
    
    return None

def parse_iso_duration(duration):
    """Convert ISO 8601 duration to readable format"""
    # Example: PT15M -> 15 min, PT1H30M -> 1 hr 30 min
    if not duration:
        return None
    
    hours = re.search(r'(\d+)H', duration)
    minutes = re.search(r'(\d+)M', duration)
    
    result = []
    if hours:
        result.append(f"{hours.group(1)} hr")
    if minutes:
        result.append(f"{minutes.group(1)} min")
    
    return " ".join(result) if result else None

def extract_servings(soup):
    """Extract servings/yield"""
    # Try JSON-LD
    json_ld = soup.find('script', type='application/ld+json')
    if json_ld:
        import json
        try:
            data = json.loads(json_ld.string)
            if isinstance(data, list):
                data = data[0]
            if data.get('@type') == 'Recipe':
                if data.get('recipeYield'):
                    yield_val = data['recipeYield']
                    if isinstance(yield_val, list):
                        yield_val = yield_val[0]
                    return str(yield_val)
        except:
            pass
    
    # Try to find in HTML
    servings_elem = soup.find(class_=re.compile('servings?|yield', re.I))
    if servings_elem:
        return servings_elem.get_text().strip()
    
    # Try regex
    text = soup.get_text()
    match = re.search(r'(?:servings?|yield|serves)[:\s]*([0-9]+(?:\s*-\s*[0-9]+)?)', text, re.I)
    if match:
        return match.group(1)
    
    return None

def extract_ingredients(soup):
    """Extract ingredients list"""
    ingredients = []
    
    # Try JSON-LD first
    json_ld = soup.find('script', type='application/ld+json')
    if json_ld:
        import json
        try:
            data = json.loads(json_ld.string)
            if isinstance(data, list):
                data = data[0]
            if data.get('@type') == 'Recipe' and data.get('recipeIngredient'):
                ingredients = data['recipeIngredient']
                if ingredients:
                    return [ing.strip() for ing in ingredients if ing.strip()]
        except:
            pass
    
    # Try common ingredient container classes
    ingredient_containers = soup.find_all(class_=re.compile('ingredient', re.I))
    for container in ingredient_containers:
        # Look for list items
        items = container.find_all('li')
        if items:
            for item in items:
                text = item.get_text().strip()
                if text and len(text) > 2:
                    ingredients.append(text)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_ingredients = []
    for ing in ingredients:
        if ing not in seen:
            seen.add(ing)
            unique_ingredients.append(ing)
    
    return unique_ingredients if unique_ingredients else ["Ingredients not found"]

def extract_instructions(soup):
    """Extract cooking instructions"""
    instructions = []
    
    # Try JSON-LD first
    json_ld = soup.find('script', type='application/ld+json')
    if json_ld:
        import json
        try:
            data = json.loads(json_ld.string)
            if isinstance(data, list):
                data = data[0]
            if data.get('@type') == 'Recipe' and data.get('recipeInstructions'):
                steps = data['recipeInstructions']
                if isinstance(steps, list):
                    for step in steps:
                        if isinstance(step, dict) and step.get('text'):
                            instructions.append(step['text'].strip())
                        elif isinstance(step, str):
                            instructions.append(step.strip())
                elif isinstance(steps, str):
                    instructions.append(steps.strip())
                
                if instructions:
                    return instructions
        except:
            pass
    
    # Try common instruction container classes
    instruction_containers = soup.find_all(class_=re.compile('instruction|direction|step|method', re.I))
    for container in instruction_containers:
        # Look for ordered list items
        items = container.find_all('li')
        if items:
            for item in items:
                text = item.get_text().strip()
                if text and len(text) > 5:
                    instructions.append(text)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_instructions = []
    for inst in instructions:
        if inst not in seen:
            seen.add(inst)
            unique_instructions.append(inst)
    
    return unique_instructions if unique_instructions else ["Instructions not found"]

def extract_image(soup):
    """Extract recipe image URL"""
    # Try JSON-LD
    json_ld = soup.find('script', type='application/ld+json')
    if json_ld:
        import json
        try:
            data = json.loads(json_ld.string)
            if isinstance(data, list):
                data = data[0]
            if data.get('@type') == 'Recipe' and data.get('image'):
                image = data['image']
                if isinstance(image, list):
                    image = image[0]
                if isinstance(image, dict):
                    image = image.get('url', '')
                return image
        except:
            pass
    
    # Try og:image
    og_image = soup.find('meta', property='og:image')
    if og_image and og_image.get('content'):
        return og_image['content']
    
    # Try first large image
    images = soup.find_all('img')
    for img in images:
        src = img.get('src', '')
        if 'recipe' in src.lower() or 'food' in src.lower():
            return src
    
    return None

def extract_recipe_from_image(image_base64, author):
    """
    Use Claude AI to extract recipe from an image
    """
    import base64
    import json
    import time
    
    # This requires the Anthropic API
    try:
        from anthropic import Anthropic
    except ImportError:
        raise Exception("Please install anthropic package: pip install anthropic")
    
    # Get API key from environment variable
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    
    if not api_key:
        raise Exception("ANTHROPIC_API_KEY environment variable not set")
    
    client = Anthropic(api_key=api_key)
    
    # Retry logic for overloaded errors
    max_retries = 5
    retry_delay = 3  # seconds
    
    for attempt in range(max_retries):
        try:
            # Call Claude with the image
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": image_base64,
                                },
                            },
                            {
                                "type": "text",
                                "text": """Please extract the recipe from this image. The image may be from a printed cookbook or a handwritten recipe.

Extract and return the recipe in the following JSON format. If the recipe has multiple sections (like a main recipe plus toppings, frosting, sauce, etc.), include them as separate sections:

{
    "title": "Recipe name",
    "description": "Brief description",
    "sections": [
        {
            "name": "Main Recipe" or null for unnamed section,
            "ingredients": ["ingredient 1", "ingredient 2", ...],
            "instructions": ["step 1", "step 2", ...]
        },
        {
            "name": "Topping" or "Frosting" or "Sauce" etc.,
            "ingredients": ["ingredient 1", "ingredient 2", ...],
            "instructions": ["step 1", "step 2", ...]
        }
    ],
    "prepTime": "prep time (e.g., '15 min')",
    "cookTime": "cook time (e.g., '30 min')", 
    "servings": "number of servings (e.g., '4 servings')"
}

For recipes with only one section, still use the sections array with a single section where name is null.
For example, a soup with separate croutons would have two sections: one for the soup and one for the croutons.

If any field is not clearly visible, use "N/A" for times/servings or empty arrays for lists.
Return ONLY the JSON, no other text."""
                            }
                        ],
                    }
                ],
            )
            
            # If successful, break out of retry loop
            break
            
        except Exception as e:
            error_msg = str(e)
            # Check if it's an overloaded error
            if 'overloaded' in error_msg.lower() and attempt < max_retries - 1:
                # Wait and retry with exponential backoff
                wait_time = retry_delay * (2 ** attempt)  # 3, 6, 12, 24, 48 seconds
                print(f"API overloaded, waiting {wait_time} seconds before retry {attempt + 2}/{max_retries}...")
                time.sleep(wait_time)
                continue
            else:
                # If it's a different error or we're out of retries, raise it
                if 'overloaded' in error_msg.lower():
                    raise Exception(
                        "The AI service is very busy right now with too many requests. "
                        "This usually happens during peak hours (business hours in the US). "
                        "Please try again in 10-30 minutes, or use Manual Entry to add your recipe now. "
                        "The scanner works best early morning or late evening!"
                    )
                raise e
    
    # Extract the text response
    response_text = message.content[0].text
    
    # Clean up any markdown code fences
    response_text = response_text.strip()
    if response_text.startswith('```json'):
        response_text = response_text[7:]
    if response_text.startswith('```'):
        response_text = response_text[3:]
    if response_text.endswith('```'):
        response_text = response_text[:-3]
    response_text = response_text.strip()
    
    # Parse JSON
    try:
        recipe_data = json.loads(response_text)
        recipe_data['source'] = author
        return recipe_data
    except json.JSONDecodeError as e:
        raise Exception(f"Could not parse recipe data from AI response: {e}")

@app.route('/api/extract', methods=['POST'])
def extract_recipe():
    """API endpoint to extract recipe from URL"""
    try:
        data = request.json
        url = data.get('url')
        
        if not url:
            return jsonify({
                'success': False,
                'error': 'No URL provided'
            }), 400
        
        recipe = extract_recipe_data(url)
        
        return jsonify({
            'success': True,
            'recipe': recipe
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

@app.route('/api/scan', methods=['POST'])
def scan_recipe():
    """API endpoint to scan recipe from image"""
    try:
        data = request.json
        image_data = data.get('image', '')
        author = data.get('author', 'Unknown')
        
        if not image_data:
            return jsonify({
                'success': False,
                'error': 'No image data provided'
            }), 400
        
        # Remove data URL prefix if present
        if 'base64,' in image_data:
            image_data = image_data.split('base64,')[1]
        
        recipe = extract_recipe_from_image(image_data, author)
        
        return jsonify({
            'success': True,
            'recipe': recipe
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({
        'status': 'healthy',
        'message': 'Recipe API is running'
    })

@app.route('/', methods=['GET'])
def home():
    """Root endpoint"""
    return jsonify({
        'message': 'Recipe Cookbook API',
        'version': '1.0',
        'endpoints': {
            '/api/extract': 'POST - Extract recipe from URL',
            '/api/scan': 'POST - Scan recipe from image',
            '/health': 'GET - Health check'
        }
    })

if __name__ == '__main__':
    # Run the app
    app.run(host='0.0.0.0', port=PORT, debug=False)
