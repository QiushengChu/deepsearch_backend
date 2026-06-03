#!/usr/bin/env python3
"""
Update generate_cv.py to merge new skills into existing SKILLS list.
New skills: React, TypeScript, NodeJS, FastAPI, Fullstack
"""

import sys

file_path = 'generate_cv.py'

with open(file_path, 'r') as f:
    content = f.read()

# The current SKILLS block:
old_skills_block = '''SKILLS = [
    ("Cyber Security", "Vulnerability Management, Security Assessments, Remediation Coordination, CVSS Scoring, Penetration Testing Coordination, Malicious File Scanning"),
    ("Technical Analysis", "Requirements Gathering, Solution Design, Stakeholder Management, Systems Integration, Technical Documentation"),
    ("Enterprise Systems", "Portal Management, Architecture Collaboration, Cross-Platform Integration"),
    ("Tools & Technologies", "JIRA, Confluence, CVSS Frameworks, Security Assessment Tools, Microsoft Office Suite"),
    ("Soft Skills", "Communication, Leadership, Problem Solving, Team Collaboration, Community Building"),
]'''

# Merged new skills:
# - Add "Fullstack Development" category with React, TypeScript, NodeJS, FastAPI
# - Also add these to Tools & Technologies
new_skills_block = '''SKILLS = [
    ("Cyber Security", "Vulnerability Management, Security Assessments, Remediation Coordination, CVSS Scoring, Penetration Testing Coordination, Malicious File Scanning"),
    ("Technical Analysis", "Requirements Gathering, Solution Design, Stakeholder Management, Systems Integration, Technical Documentation"),
    ("Enterprise Systems", "Portal Management, Architecture Collaboration, Cross-Platform Integration"),
    ("Fullstack Development", "React, TypeScript, NodeJS, FastAPI"),
    ("Tools & Technologies", "JIRA, Confluence, CVSS Frameworks, Security Assessment Tools, Microsoft Office Suite, React, TypeScript, NodeJS, FastAPI"),
    ("Soft Skills", "Communication, Leadership, Problem Solving, Team Collaboration, Community Building"),
]'''

if old_skills_block in content:
    content = content.replace(old_skills_block, new_skills_block)
    with open(file_path, 'w') as f:
        f.write(content)
    print("[OK] Successfully updated SKILLS in generate_cv.py")
    sys.exit(0)
else:
    print("ERROR: Could not find the original SKILLS block in generate_cv.py")
    # Let's try to find it with more flexible matching
    import re
    # Fallback: find SKILLS assignment
    match = re.search(r'SKILLS = \[.*?\]', content, re.DOTALL)
    if match:
        print(f"Found SKILLS block at position {match.start()}:{match.end()}")
        print("But exact string match failed. Please check the formatting.")
    sys.exit(1)
