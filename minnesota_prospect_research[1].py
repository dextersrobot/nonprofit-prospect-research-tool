#!/usr/bin/env python3
"""
Minnesota Corporate Prospect Research Tool
==========================================
Automated prospect research for Minnesota-based Fortune 500 companies
to support Children's Cancer Research Fund (CCRF) development efforts.

Analyzes 3 Minnesota companies:
- Target Corporation (TGT) - Minneapolis
- 3M Company (MMM) - St. Paul  
- UnitedHealth Group (UNH) - Minnetonka

Data Sources:
- SEC EDGAR (company filings and XBRL financials)
- ProPublica Nonprofit Explorer (990 foundation data)

Author: [Your Name]
Date: January 2026
APRA Ethics Compliant: Uses only publicly available information
"""

import json
import requests
from datetime import datetime
from typing import Dict, List, Optional
import time
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ============================================================================
# CONFIGURATION
# ============================================================================

# Minnesota companies to analyze
MINNESOTA_COMPANIES = [
    {"ticker": "TGT", "name": "Target Corporation", "city": "Minneapolis"},
    {"ticker": "MMM", "name": "3M Company", "city": "St. Paul"},
    {"ticker": "UNH", "name": "UnitedHealth Group", "city": "Minnetonka"},
]

USER_AGENT = "CCRFProspectResearch/1.0 (research@ccrf.org)"
SEC_BASE_URL = "https://data.sec.gov"
PROPUBLICA_BASE_URL = "https://projects.propublica.org/nonprofits/api/v2"

# ============================================================================
# DATA COLLECTION FUNCTIONS
# ============================================================================

def get_cik_from_ticker(ticker: str) -> Optional[str]:
    """Look up SEC CIK number from stock ticker."""
    try:
        headers = {"User-Agent": USER_AGENT}
        response = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers)
        response.raise_for_status()
        
        for entry in response.json().values():
            if entry.get('ticker', '').upper() == ticker.upper():
                return str(entry['cik_str']).zfill(10)
        return None
    except Exception as e:
        print(f"  Error getting CIK: {e}")
        return None


def get_company_info(ticker: str, cik: str) -> Dict:
    """Fetch company information from SEC EDGAR."""
    try:
        headers = {"User-Agent": USER_AGENT}
        time.sleep(0.1)
        
        response = requests.get(f"{SEC_BASE_URL}/submissions/CIK{cik}.json", headers=headers)
        response.raise_for_status()
        data = response.json()
        
        return {
            "cik": cik,
            "name": data.get("name", ""),
            "ticker": ticker.upper(),
            "sic": data.get("sic", ""),
            "sic_description": data.get("sicDescription", ""),
            "state": data.get("stateOfIncorporation", ""),
            "fiscal_year_end": data.get("fiscalYearEnd", ""),
            "phone": data.get("phone", ""),
            "business_address": data.get("addresses", {}).get("business", {}),
        }
    except Exception as e:
        return {"error": str(e)}


def get_company_financials(cik: str) -> Dict:
    """Fetch XBRL financial data from SEC."""
    try:
        headers = {"User-Agent": USER_AGENT}
        time.sleep(0.1)
        
        response = requests.get(f"{SEC_BASE_URL}/api/xbrl/companyfacts/CIK{cik}.json", headers=headers)
        response.raise_for_status()
        
        facts = response.json()
        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        
        def get_latest(concept: str) -> Optional[Dict]:
            if concept not in us_gaap:
                return None
            usd_values = us_gaap[concept].get("units", {}).get("USD", [])
            annual = [v for v in usd_values if v.get("form") == "10-K"]
            if annual:
                latest = max(annual, key=lambda x: x.get("end", ""))
                return {"value": latest.get("val"), "period_end": latest.get("end")}
            return None
        
        return {
            "revenue": get_latest("Revenues") or get_latest("RevenueFromContractWithCustomerExcludingAssessedTax"),
            "net_income": get_latest("NetIncomeLoss"),
            "total_assets": get_latest("Assets"),
            "cash_and_equivalents": get_latest("CashAndCashEquivalentsAtCarryingValue"),
            "stockholders_equity": get_latest("StockholdersEquity"),
        }
    except Exception as e:
        return {"error": str(e)}


def search_foundation(company_name: str) -> Optional[Dict]:
    """Search for corporate foundation in ProPublica 990 data."""
    try:
        # Try different search terms
        search_terms = [
            f"{company_name} foundation",
            f"{company_name.split()[0]} foundation",
        ]
        
        for term in search_terms:
            response = requests.get(f"{PROPUBLICA_BASE_URL}/search.json", params={"q": term})
            if response.status_code == 200:
                orgs = response.json().get("organizations", [])
                for org in orgs[:10]:
                    org_name = org.get("name", "").upper()
                    company_word = company_name.split()[0].upper()
                    if company_word in org_name and "FOUNDATION" in org_name:
                        return {
                            "name": org.get("name"),
                            "ein": org.get("ein"),
                            "city": org.get("city"),
                            "state": org.get("state"),
                        }
            time.sleep(0.1)
        return None
    except Exception as e:
        return None


def get_foundation_details(ein: str) -> Optional[Dict]:
    """Get detailed 990 data for a foundation."""
    try:
        response = requests.get(f"{PROPUBLICA_BASE_URL}/organizations/{ein}.json")
        if response.status_code != 200:
            return None
            
        data = response.json()
        org = data.get("organization", {})
        filings = data.get("filings_with_data", [])
        
        return {
            "name": org.get("name"),
            "ein": ein,
            "total_assets": org.get("asset_amount"),
            "total_revenue": org.get("income_amount"),
            "ruling_date": org.get("ruling_date"),
            "recent_filings": [
                {
                    "year": f.get("tax_prd_yr"),
                    "revenue": f.get("totrevenue"),
                    "expenses": f.get("totfuncexpns"),
                    "assets": f.get("totassetsend"),
                    "grants_paid": f.get("contrpdpbks"),
                }
                for f in filings[:3]
            ]
        }
    except Exception as e:
        return None


# ============================================================================
# ANALYSIS FUNCTIONS  
# ============================================================================

def calculate_capacity_rating(financials: Dict) -> Dict:
    """Calculate giving capacity based on financial metrics."""
    cash = (financials.get("cash_and_equivalents") or {}).get("value", 0) or 0
    net_income = (financials.get("net_income") or {}).get("value", 0) or 0
    assets = (financials.get("total_assets") or {}).get("value", 0) or 0
    
    # Capacity score based on multiple factors
    score = (cash + net_income) / 1_000_000_000  # In billions
    
    if score > 30:
        rating = "MAJOR ($1M+)"
        color = "#27ae60"
    elif score > 15:
        rating = "LEADERSHIP ($250K-$1M)"
        color = "#f39c12"
    elif score > 5:
        rating = "PRINCIPAL ($50K-$250K)"
        color = "#3498db"
    else:
        rating = "STANDARD ($10K-$50K)"
        color = "#95a5a6"
    
    return {
        "score": score,
        "rating": rating,
        "color": color,
        "rationale": [
            f"Cash position: ${cash/1e9:.1f}B" if cash else "Cash data unavailable",
            f"Net income: ${net_income/1e9:.1f}B" if net_income else "Net income data unavailable",
            f"Total assets: ${assets/1e9:.1f}B" if assets else "Assets data unavailable",
        ]
    }


def assess_mission_alignment(company: Dict) -> Dict:
    """Assess alignment with CCRF's pediatric cancer research mission."""
    sic_desc = company.get("sic_description", "").lower()
    
    alignment_factors = []
    alignment_score = 0
    
    # Healthcare sector = strong alignment
    if any(term in sic_desc for term in ["health", "medical", "pharmaceutical", "hospital"]):
        alignment_factors.append("Healthcare sector - STRONG alignment with pediatric health mission")
        alignment_score += 3
    
    # Retail = community presence, cause marketing potential
    if any(term in sic_desc for term in ["retail", "store", "merchandise"]):
        alignment_factors.append("Retail sector - Strong community presence, cause marketing potential")
        alignment_score += 2
    
    # Manufacturing/diversified = CSR programs
    if any(term in sic_desc for term in ["manufacturing", "chemical", "industrial"]):
        alignment_factors.append("Manufacturing sector - Likely has established CSR programs")
        alignment_score += 1
    
    # Minnesota-based = local connection
    alignment_factors.append("Minnesota headquarters - Local community connection to CCRF")
    alignment_score += 2
    
    if alignment_score >= 4:
        level = "HIGH"
    elif alignment_score >= 2:
        level = "MEDIUM"
    else:
        level = "STANDARD"
    
    return {
        "level": level,
        "score": alignment_score,
        "factors": alignment_factors,
    }


# ============================================================================
# MAIN RESEARCH FUNCTION
# ============================================================================

def research_company(company_config: Dict) -> Dict:
    """Conduct full prospect research on a single company."""
    ticker = company_config["ticker"]
    print(f"\n{'='*60}")
    print(f"RESEARCHING: {company_config['name']} ({ticker})")
    print(f"Location: {company_config['city']}, Minnesota")
    print(f"{'='*60}")
    
    # Get CIK
    print("  → Fetching SEC CIK...")
    cik = get_cik_from_ticker(ticker)
    if not cik:
        return {"error": f"Could not find CIK for {ticker}"}
    
    # Get company info
    print("  → Fetching company information...")
    company_info = get_company_info(ticker, cik)
    if "error" in company_info:
        return company_info
    
    # Get financials
    print("  → Fetching XBRL financial data...")
    financials = get_company_financials(cik)
    
    # Search for foundation
    print("  → Searching for corporate foundation...")
    foundation_search = search_foundation(company_config["name"])
    foundation_details = None
    if foundation_search:
        print(f"  → Found: {foundation_search['name']}")
        foundation_details = get_foundation_details(str(foundation_search["ein"]))
    
    # Calculate capacity and alignment
    capacity = calculate_capacity_rating(financials)
    alignment = assess_mission_alignment(company_info)
    
    return {
        "ticker": ticker,
        "config": company_config,
        "company": company_info,
        "financials": financials,
        "foundation": {
            "search": foundation_search,
            "details": foundation_details,
        },
        "capacity": capacity,
        "alignment": alignment,
        "researched_at": datetime.now().isoformat(),
    }


def research_all_companies() -> List[Dict]:
    """Research all Minnesota companies."""
    print("\n" + "="*70)
    print("MINNESOTA CORPORATE PROSPECT RESEARCH")
    print("Children's Cancer Research Fund")
    print("="*70)
    print(f"\nAnalyzing {len(MINNESOTA_COMPANIES)} Minnesota Fortune 500 companies...")
    
    results = []
    for company in MINNESOTA_COMPANIES:
        result = research_company(company)
        results.append(result)
        
        # Print summary
        if "error" not in result:
            fin = result["financials"]
            cap = result["capacity"]
            print(f"\n  SUMMARY:")
            print(f"  • Industry: {result['company'].get('sic_description', 'N/A')}")
            ni = (fin.get("net_income") or {}).get("value")
            print(f"  • Net Income: ${ni/1e9:.2f}B" if ni else "  • Net Income: N/A")
            cash = (fin.get("cash_and_equivalents") or {}).get("value")
            print(f"  • Cash Position: ${cash/1e9:.2f}B" if cash else "  • Cash Position: N/A")
            print(f"  • Capacity Rating: {cap['rating']}")
            print(f"  • Mission Alignment: {result['alignment']['level']}")
    
    return results


# ============================================================================
# VISUALIZATION FUNCTIONS
# ============================================================================

def create_visualizations(results: List[Dict], output_path: str):
    """Create comprehensive visualization dashboard."""
    
    # Filter successful results
    valid_results = [r for r in results if "error" not in r]
    if not valid_results:
        print("No valid results to visualize")
        return
    
    # Extract data
    tickers = [r["ticker"] for r in valid_results]
    companies = [r["config"]["name"] for r in valid_results]
    cities = [r["config"]["city"] for r in valid_results]
    
    # Financial data (in billions)
    net_incomes = []
    cash_positions = []
    total_assets = []
    revenues = []
    
    for r in valid_results:
        fin = r["financials"]
        ni = (fin.get("net_income") or {}).get("value", 0) or 0
        cash = (fin.get("cash_and_equivalents") or {}).get("value", 0) or 0
        assets = (fin.get("total_assets") or {}).get("value", 0) or 0
        rev = (fin.get("revenue") or {}).get("value", 0) or 0
        
        net_incomes.append(ni / 1e9)
        cash_positions.append(cash / 1e9)
        total_assets.append(assets / 1e9)
        revenues.append(rev / 1e9)
    
    capacity_scores = [r["capacity"]["score"] for r in valid_results]
    capacity_ratings = [r["capacity"]["rating"] for r in valid_results]
    capacity_colors = [r["capacity"]["color"] for r in valid_results]
    
    # Set up figure
    fig = plt.figure(figsize=(18, 14))
    fig.patch.set_facecolor('white')
    
    # Title
    fig.suptitle('Minnesota Corporate Prospect Research Analysis\nChildren\'s Cancer Research Fund (CCRF)', 
                 fontsize=18, fontweight='bold', y=0.98)
    
    # Subtitle
    fig.text(0.5, 0.94, f'Analysis Date: {datetime.now().strftime("%B %d, %Y")} | Companies: {", ".join(tickers)}',
             ha='center', fontsize=11, color='#7f8c8d')
    
    # Color palette
    colors = ['#e74c3c', '#3498db', '#2ecc71']  # Red, Blue, Green for TGT, MMM, UNH
    
    # =========================================================================
    # Chart 1: Revenue & Net Income Comparison (Top Left)
    # =========================================================================
    ax1 = fig.add_subplot(2, 3, 1)
    x = np.arange(len(tickers))
    width = 0.35
    
    bars1 = ax1.bar(x - width/2, revenues, width, label='Revenue', color='#3498db', alpha=0.8)
    bars2 = ax1.bar(x + width/2, net_incomes, width, label='Net Income', color='#2ecc71', alpha=0.8)
    
    ax1.set_ylabel('Billions (USD)', fontweight='bold')
    ax1.set_title('Revenue vs Net Income', fontsize=12, fontweight='bold', pad=10)
    ax1.set_xticks(x)
    ax1.set_xticklabels(tickers, fontweight='bold')
    ax1.legend(loc='upper right')
    ax1.grid(axis='y', alpha=0.3, linestyle='--')
    ax1.set_axisbelow(True)
    
    # Add value labels
    for bar in bars1:
        if bar.get_height() > 0:
            ax1.annotate(f'${bar.get_height():.1f}B',
                        xy=(bar.get_x() + bar.get_width()/2, bar.get_height()),
                        xytext=(0, 3), textcoords="offset points",
                        ha='center', va='bottom', fontsize=9, fontweight='bold')
    
    for bar in bars2:
        if bar.get_height() > 0:
            ax1.annotate(f'${bar.get_height():.1f}B',
                        xy=(bar.get_x() + bar.get_width()/2, bar.get_height()),
                        xytext=(0, 3), textcoords="offset points",
                        ha='center', va='bottom', fontsize=9, fontweight='bold')
    
    # =========================================================================
    # Chart 2: Total Assets Comparison (Top Middle)
    # =========================================================================
    ax2 = fig.add_subplot(2, 3, 2)
    bars = ax2.bar(tickers, total_assets, color=colors, alpha=0.8, edgecolor='white', linewidth=2)
    
    ax2.set_ylabel('Billions (USD)', fontweight='bold')
    ax2.set_title('Total Assets by Company', fontsize=12, fontweight='bold', pad=10)
    ax2.grid(axis='y', alpha=0.3, linestyle='--')
    ax2.set_axisbelow(True)
    
    for bar, ticker in zip(bars, tickers):
        ax2.annotate(f'${bar.get_height():.1f}B',
                    xy=(bar.get_x() + bar.get_width()/2, bar.get_height()),
                    xytext=(0, 3), textcoords="offset points",
                    ha='center', va='bottom', fontsize=10, fontweight='bold')
    
    # =========================================================================
    # Chart 3: Cash Position Pie Chart (Top Right)
    # =========================================================================
    ax3 = fig.add_subplot(2, 3, 3)
    
    # Filter non-zero values
    pie_data = [(t, c) for t, c in zip(tickers, cash_positions) if c > 0]
    if pie_data:
        pie_tickers, pie_values = zip(*pie_data)
        pie_colors = [colors[tickers.index(t)] for t in pie_tickers]
        
        wedges, texts, autotexts = ax3.pie(
            pie_values, 
            labels=pie_tickers,
            autopct='%1.1f%%',
            colors=pie_colors,
            explode=[0.02] * len(pie_values),
            shadow=True,
            startangle=90
        )
        
        for autotext in autotexts:
            autotext.set_fontweight('bold')
            autotext.set_fontsize(10)
        
        total = sum(pie_values)
        ax3.text(0, 0, f'Total\n${total:.1f}B', ha='center', va='center', 
                fontsize=12, fontweight='bold')
    
    ax3.set_title('Cash Position Distribution', fontsize=12, fontweight='bold', pad=10)
    
    # =========================================================================
    # Chart 4: Giving Capacity Assessment (Bottom Left)
    # =========================================================================
    ax4 = fig.add_subplot(2, 3, 4)
    
    y_pos = np.arange(len(tickers))
    bars = ax4.barh(y_pos, capacity_scores, color=capacity_colors, alpha=0.8, 
                   edgecolor='white', linewidth=2)
    
    ax4.set_yticks(y_pos)
    ax4.set_yticklabels([f"{t}\n({c})" for t, c in zip(tickers, cities)], fontweight='bold')
    ax4.set_xlabel('Capacity Score (Cash + Net Income in $B)', fontweight='bold')
    ax4.set_title('Giving Capacity Assessment', fontsize=12, fontweight='bold', pad=10)
    ax4.grid(axis='x', alpha=0.3, linestyle='--')
    ax4.set_axisbelow(True)
    
    # Add capacity tier labels
    for i, (bar, rating) in enumerate(zip(bars, capacity_ratings)):
        ax4.annotate(rating,
                    xy=(bar.get_width() + 1, bar.get_y() + bar.get_height()/2),
                    va='center', fontsize=9, fontweight='bold',
                    color=capacity_colors[i])
    
    # =========================================================================
    # Chart 5: Company Comparison Radar/Summary Table (Bottom Middle)
    # =========================================================================
    ax5 = fig.add_subplot(2, 3, 5)
    ax5.axis('off')
    
    # Create summary table
    table_data = []
    for i, r in enumerate(valid_results):
        fin = r["financials"]
        rev = (fin.get("revenue") or {}).get("value", 0) or 0
        ni = (fin.get("net_income") or {}).get("value", 0) or 0
        cash = (fin.get("cash_and_equivalents") or {}).get("value", 0) or 0
        
        foundation = "✓" if r["foundation"]["search"] else "—"
        alignment = r["alignment"]["level"]
        
        table_data.append([
            r["ticker"],
            r["config"]["city"],
            f"${rev/1e9:.1f}B" if rev else "N/A",
            f"${ni/1e9:.1f}B" if ni else "N/A",
            f"${cash/1e9:.1f}B" if cash else "N/A",
            foundation,
            alignment
        ])
    
    col_labels = ['Ticker', 'City', 'Revenue', 'Net Income', 'Cash', 'Foundation', 'Alignment']
    
    table = ax5.table(
        cellText=table_data,
        colLabels=col_labels,
        cellLoc='center',
        loc='center',
        colColours=['#1a5276'] * len(col_labels)
    )
    
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.2, 2.0)
    
    # Style header
    for i in range(len(col_labels)):
        table[(0, i)].set_text_props(color='white', fontweight='bold')
    
    # Color code rows by company
    for i in range(len(valid_results)):
        for j in range(len(col_labels)):
            table[(i+1, j)].set_facecolor(colors[i] + '20')  # Light version of color
    
    ax5.set_title('Prospect Summary Matrix', fontsize=12, fontweight='bold', pad=20, y=0.95)
    
    # =========================================================================
    # Chart 6: Recommended Priority & Next Steps (Bottom Right)
    # =========================================================================
    ax6 = fig.add_subplot(2, 3, 6)
    ax6.axis('off')
    
    # Sort by capacity score for priority ranking
    sorted_results = sorted(valid_results, key=lambda x: x["capacity"]["score"], reverse=True)
    
    priority_text = "RECOMMENDED OUTREACH PRIORITY\n" + "="*40 + "\n\n"
    
    for i, r in enumerate(sorted_results, 1):
        medal = ["#1", "#2", "#3"][i-1] if i <= 3 else f"{i}."
        priority_text += f"{medal} {r['config']['name']} ({r['ticker']})\n"
        priority_text += f"   Capacity: {r['capacity']['rating']}\n"
        priority_text += f"   Alignment: {r['alignment']['level']}\n"
        if r["foundation"]["search"]:
            priority_text += f"   Foundation: {r['foundation']['search']['name']}\n"
        priority_text += "\n"
    
    priority_text += "="*40 + "\n"
    priority_text += "NEXT STEPS:\n"
    priority_text += "• Research executive connections\n"
    priority_text += "• Review foundation grant history\n"
    priority_text += "• Identify internal champions\n"
    priority_text += "• Prepare tailored proposals"
    
    ax6.text(0.1, 0.95, priority_text, transform=ax6.transAxes, fontsize=10,
            verticalalignment='top', fontfamily='monospace',
            bbox=dict(boxstyle='round', facecolor='#ecf0f1', alpha=0.8))
    
    ax6.set_title('Priority Ranking & Next Steps', fontsize=12, fontweight='bold', pad=10)
    
    # =========================================================================
    # Save figure
    # =========================================================================
    plt.tight_layout(rect=[0, 0.02, 1, 0.92])
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white', edgecolor='none')
    plt.close()
    
    print(f"\n📊 Dashboard saved to: {output_path}")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution function."""
    
    # Research all companies
    results = research_all_companies()
    
    # Save individual JSON profiles
    output_dir = "/home/claude/prospect_research_demo"
    for result in results:
        if "error" not in result:
            filename = f"{output_dir}/{result['ticker']}_prospect_profile.json"
            with open(filename, 'w') as f:
                json.dump(result, f, indent=2, default=str)
            print(f"\n💾 Saved: {filename}")
    
    # Save combined results
    combined_file = f"{output_dir}/minnesota_prospects_combined.json"
    with open(combined_file, 'w') as f:
        json.dump({
            "analysis_date": datetime.now().isoformat(),
            "companies_analyzed": len(results),
            "data_sources": ["SEC EDGAR", "ProPublica Nonprofit Explorer"],
            "results": results
        }, f, indent=2, default=str)
    
    # Generate visualization
    viz_path = f"{output_dir}/minnesota_prospect_dashboard.png"
    create_visualizations(results, viz_path)
    
    # Print final summary
    print("\n" + "="*70)
    print("RESEARCH COMPLETE")
    print("="*70)
    
    valid = [r for r in results if "error" not in r]
    print(f"\n✅ Successfully analyzed {len(valid)} of {len(results)} companies")
    print(f"\nFiles generated:")
    print(f"  • Individual profiles: {len(valid)} JSON files")
    print(f"  • Combined analysis: minnesota_prospects_combined.json")
    print(f"  • Visual dashboard: minnesota_prospect_dashboard.png")
    
    # Priority ranking
    print("\n📋 PRIORITY RANKING (by giving capacity):")
    sorted_results = sorted(valid, key=lambda x: x["capacity"]["score"], reverse=True)
    for i, r in enumerate(sorted_results, 1):
        print(f"  {i}. {r['config']['name']} ({r['ticker']}) - {r['capacity']['rating']}")


if __name__ == "__main__":
    main()
