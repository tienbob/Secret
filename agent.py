import os
import json
import re
import time
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

from langchain.agents import create_agent
from langchain.tools import tool
from tavily import TavilyClient
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ContactInfo:
    """Structured contact information extracted from search results"""
    name: str = None
    title: str = None
    email: str = None
    linkedin_url: str = None
    source_query: str = None
    search_attempt: int = None

    def to_dict(self):
        return {
            "name": self.name or "",
            "title": self.title or "",
            "email": self.email or "",
            "linkedin_url": self.linkedin_url or "",
            "source_query": self.source_query or "",
            "search_attempt": self.search_attempt or 0
        }


@tool
def search_executive_info(query: str) -> str:
    """Search for executive information using Tavily API.
    
    Args:
        query: Search query for finding CEO/CTO information
        
    Returns:
        Formatted search results as string
    """
    try:
        tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
        response = tavily_client.search(
            query=query,
            max_results=5,
            include_domains=["linkedin.com", "crunchbase.com", "wikipedia.org"],
            search_depth="advanced"
        )
        results = response.get("results", [])
        
        if results:
            formatted = f"Search Results for '{query}':\n"
            for i, result in enumerate(results, 1):
                formatted += f"\n{i}. Title: {result.get('title', 'N/A')}\n"
                formatted += f"   URL: {result.get('url', 'N/A')}\n"
                formatted += f"   Content: {result.get('content', 'N/A')[:300]}\n"
            return formatted
        else:
            return f"No results found for: {query}"
    except Exception as e:
        logger.error(f"Tavily search failed for query '{query}': {str(e)}")
        return f"Search error for '{query}': {str(e)}"


class ExecutiveContactFinder:
    """
    Agent for finding CEO/CTO contact information using LangChain + Tavily
    Uses the new create_agent() API from LangChain v1.0+
    """
    
    def __init__(self):
        # LLM Model Selection
        llm_type = os.getenv("LLM_MODEL_TYPE", "gemini").lower()
        
        if llm_type == "ollama":
            ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
            logger.info(f"Using Ollama: {ollama_model} at {ollama_base_url}")
            self.llm = ChatOllama(
                base_url=ollama_base_url,
                model=ollama_model,
                temperature=0
            )
        elif llm_type == "gemini":
            google_api_key = os.getenv("GOOGLE_API_KEY")
            logger.info("Using Google Gemini")
            self.llm = ChatGoogleGenerativeAI(
                model="gemini-pro",
                temperature=0,
                google_api_key=google_api_key
            )
        else:
            raise ValueError(f"Unknown LLM_MODEL_TYPE: {llm_type}. Use 'ollama' or 'gemini'")
        
        self.search_delay = float(os.getenv("SEARCH_DELAY_SECONDS", "2"))
        self.max_retries = int(os.getenv("MAX_RETRY_ATTEMPTS", "3"))
        
        # Initialize agent with tools
        self.agent = self._setup_agent()
    
    def _setup_agent(self):
        """Set up the agent using LangChain v1.0+ create_agent() API
        
        Note: Ollama models typically don't support tool calling. We create
        an agent without tools and use manual search + LLM extraction instead.
        """
        
        system_prompt = """You are an expert at extracting executive contact information from search results.
Given search results, extract CEO and CTO details: name, title, email, and LinkedIn profile.
Return ONLY a JSON object (no additional text) with this structure:
{
  "ceo": {"name": "...", "title": "...", "email": "...", "linkedin_url": "..."},
  "cto": {"name": "...", "title": "...", "email": "...", "linkedin_url": "..."},
  "found": true/false
}
Use empty strings for missing information."""
        
        # Create a simple agent without tools for Ollama
        # This avoids tool_binding issues with local models
        agent = create_agent(
            model=self.llm,
            tools=[],
            system_prompt=system_prompt,
            name="executive_contact_finder"
        )
        
        return agent
    

    
    def find_executive_contacts(
        self, 
        company_name: str, 
        company_website: Optional[str] = None
    ) -> Dict[str, Any]:
        """Find CEO and CTO contact information for a company
        
        Process:
        1. Try multiple search queries
        2. For each result, use LLM to extract structured information
        3. Return contact details with confidence scores
        
        Args:
            company_name: Name of the company
            company_website: Optional company website URL
        
        Returns:
            Dictionary with CEO and CTO contact info, search stats
        """
        result = {
            "company_name": company_name,
            "ceo": ContactInfo().to_dict(),
            "cto": ContactInfo().to_dict(),
            "search_status": "not_found",
            "search_attempts": 0,
            "search_confidence": 0.0
        }
        
        # Define retry queries
        queries = [
            f"{company_name} CEO CTO leadership executives",
            f"{company_name} founder COO chief technology officer",
            f"{company_name} site:linkedin.com CEO CTO"
        ]
        
        attempt = 0
        for query in queries:
            attempt += 1
            result["search_attempts"] = attempt
            
            try:
                logger.info(f"Attempt {attempt}/3 for {company_name}: {query}")
                
                # Manual search using Tavily
                try:
                    tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
                    response = tavily_client.search(
                        query=query,
                        max_results=5,
                        include_domains=["linkedin.com", "crunchbase.com", "wikipedia.org"],
                        search_depth="advanced"
                    )
                    results = response.get("results", [])
                    
                    if results:
                        search_context = f"Search Results for '{query}':\n\n"
                        for i, result_item in enumerate(results, 1):
                            search_context += f"{i}. Title: {result_item.get('title', 'N/A')}\n"
                            search_context += f"   URL: {result_item.get('url', 'N/A')}\n"
                            search_context += f"   Content: {result_item.get('content', 'N/A')[:400]}\n\n"
                    else:
                        search_context = f"No search results found for: {query}"
                except Exception as e:
                    logger.error(f"Search failed: {str(e)}")
                    search_context = f"Search error: {str(e)}"
                
                # Use LLM to extract structured information
                extraction_prompt = f"""Extract executive information for {company_name} from these search results:

{search_context}

Return ONLY a JSON object (absolutely no other text):
{{
  "ceo": {{"name": "", "title": "", "email": "", "linkedin_url": ""}},
  "cto": {{"name": "", "title": "", "email": "", "linkedin_url": ""}},
  "found": false
}}"""
                
                # Invoke agent to get extraction
                response = self.agent.invoke({
                    "messages": [{"role": "user", "content": extraction_prompt}]
                })
                
                # Extract output from response
                output = ""
                if isinstance(response, dict):
                    if "messages" in response and len(response["messages"]) > 0:
                        msg = response["messages"][-1]
                        if hasattr(msg, 'content'):
                            output = msg.content
                        else:
                            output = str(msg)
                elif isinstance(response, str):
                    output = response
                
                logger.debug(f"LLM response: {output[:200]}")
                
                # Parse JSON from output
                if output and len(output) > 10:
                    try:
                        # Extract JSON from response (in case there's extra text)
                        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', output, re.DOTALL)
                        if json_match:
                            extracted = json.loads(json_match.group())
                            
                            result["search_status"] = "found"
                            result["search_confidence"] = 0.7 if attempt == 1 else (0.5 if attempt == 2 else 0.3)
                            
                            # Update CEO info
                            if extracted.get("ceo") and any(v for v in extracted["ceo"].values()):
                                result["ceo"] = {
                                    "name": extracted["ceo"].get("name", ""),
                                    "title": extracted["ceo"].get("title", ""),
                                    "email": extracted["ceo"].get("email", ""),
                                    "linkedin_url": extracted["ceo"].get("linkedin_url", ""),
                                    "source_query": query,
                                    "search_attempt": attempt
                                }
                            
                            # Update CTO info
                            if extracted.get("cto") and any(v for v in extracted["cto"].values()):
                                result["cto"] = {
                                    "name": extracted["cto"].get("name", ""),
                                    "title": extracted["cto"].get("title", ""),
                                    "email": extracted["cto"].get("email", ""),
                                    "linkedin_url": extracted["cto"].get("linkedin_url", ""),
                                    "source_query": query,
                                    "search_attempt": attempt
                                }
                            
                            # Stop if found
                            if extracted.get("found") or (result["ceo"]["name"] and result["cto"]["name"]):
                                break
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning(f"Could not parse JSON: {str(e)}")
                
                # Delay before next attempt
                if attempt < len(queries):
                    time.sleep(self.search_delay)
            
            except Exception as e:
                logger.error(f"Attempt {attempt} failed with error: {str(e)}")
                if attempt < len(queries):
                    time.sleep(self.search_delay)
        
        return result


def main():
    """Test the agent with a sample company"""
    finder = ExecutiveContactFinder()
    
    # Test with a known company
    result = finder.find_executive_contacts(
        company_name="OpenAI",
        company_website="https://openai.com"
    )
    
    print("Search Result:")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
