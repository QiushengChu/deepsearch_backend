

# from typing_extensions import TypedDict
# from langgraph.graph.state import StateGraph, START
# from typing_extensions import TypedDict
# from langgraph.graph.state import StateGraph, START
# from typing import Annotated, Sequence
# from langgraph.graph.message import add_messages

# # Define subgraph
# class SubgraphState(TypedDict):
#     # note that none of these keys are shared with the parent graph state
#     bar: Annotated[Sequence[str], add_messages] ##take parent messages and pass back to parent
#     baz: Annotated[Sequence[str], add_messages] ##subagent internal messages

# def subgraph_node_1(state: SubgraphState):
#     return {
#         "bar": state["bar"],
#         "baz": state["bar"] + ["Hello this is subnode 1, should be ignored"]
#     }

# def subgraph_node_2(state: SubgraphState):
#     return {
#         "bar": state["bar"] + ["Hello this is subnode 2"]
#     }

# subgraph_builder = StateGraph(SubgraphState)
# subgraph_builder.add_node(subgraph_node_1)
# subgraph_builder.add_node(subgraph_node_2)
# subgraph_builder.add_edge(START, "subgraph_node_1")
# subgraph_builder.add_edge("subgraph_node_1", "subgraph_node_2")
# subgraph = subgraph_builder.compile()

# # Define parent graph
# class ParentState(TypedDict):
#     foo: Annotated[Sequence[str], add_messages]

# def node_1(state: ParentState):
#     return {
#         "foo": state["foo"] + ["hello, this is parentnode 1"]
#     }

# def node_2(state: ParentState):
#     # Transform the state to the subgraph state
#     response = subgraph.invoke({"bar": state["foo"], "baz": []})
#     # Transform response back to the parent state
#     return {"foo": response["bar"]}


# builder = StateGraph(ParentState)
# builder.add_node("node_1", node_1)
# builder.add_node("node_2", node_2)
# builder.add_edge(START, "node_1")
# builder.add_edge("node_1", "node_2")
# graph = builder.compile()

# for chunk in graph.stream({"foo": "foo"}, subgraphs=False):
#     print(chunk)

from weasyprint import HTML, CSS

def generate_polished_pdf(html_body, css_styles, output_path="output.pdf"):
    full_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"></head>
    <body>{html_body}</body>
    </html>
    """
    HTML(string=full_html).write_pdf(
        output_path,
        stylesheets=[CSS(string=css_styles)]
    )

html_body = """
<div class="resume-container">
    <div class="accent-line"></div>
    
    <div class="header">
        <h1 class="name">Tim C</h1>
        <div class="title">Senior Cybersecurity Engineer</div>
        
        <div class="contact-info">
            <div class="contact-item">
                <span class="icon">📱</span> Mobile: [Your Mobile]
            </div>
            <div class="contact-item">
                <span class="icon">✉️</span> Email: xxx@com
            </div>
        </div>
    </div>
    
    <div class="section">
        <h2 class="section-title">About Me</h2>
        <div class="about-me">
            Senior cybersecurity engineer with deep expertise in application and infrastructure security, DevSecOps, cloud security, and penetration testing. With a strong full-stack and automation background, I design scalable security architectures, harden CI/CD and API ecosystems, and drive secure development across teams. I also specialize in AI-driven security engineering — building functional AI agents, fine-tuning LLMs for secure code analysis, and integrating intelligent workflows to enhance detection, analysis, and developer productivity.
        </div>
    </div>
    
    <div class="section">
        <h2 class="section-title">Experience</h2>
        
        <div class="experience-item">
            <div class="job-header">
                <div>
                    <div class="job-title">Senior Manager – Application Security Design Engineer</div>
                    <div class="company">Macquarie Group - Banking and Financial Service</div>
                </div>
                <div class="job-period">2023 June to Now</div>
            </div>
            <div class="job-description">
                <ul class="responsibilities">
                    <li>Designed Noname API security integration architecture with compliance requirement and developing automation for automatic instance redeployment and failover.</li>
                    <li>Executed targeted penetration testing on newly released applications and features to uncover potential security gaps.</li>
                    <li>Developed security coding templates and fortifying CI/CD pipelines to ensure adherence to best practices.</li>
                    <li>Designed and implemented API security solutions in Apigee API gateway according application requirement.</li>
                    <li>Built robust Apigee gateway proxies for banking and employee applications, implementing OAuth 2.0 for enhanced authentication.</li>
                    <li>Engineered and built a fast docker vulnerability data contextualizer to streamline the process of managing vulnerabilities.</li>
                    <li>Engineered the implementation of GitHub Advance Security for organization code repositories.</li>
                    <li>Supervised fine tune (SFTed) with QWen-2B and QLoar Llama2-7B with customized CodeQL rulesets for making specialized CodeQL query writers.</li>
                </ul>
            </div>
        </div>
        
        <div class="experience-item">
            <div class="job-header">
                <div>
                    <div class="job-title">Full-Stack Developer - Side Project</div>
                </div>
                <div class="job-period">2023 June to Now</div>
            </div>
            <div class="job-description">
                <ul class="responsibilities">
                    <li>Crafted and implemented the backend infrastructure for the Information web application using Node.js Express.</li>
                    <li>Developed a responsive frontend interface for the web application using React.js.</li>
                    <li>Built and secured CI/CD pipeline through GitHub workflows to automate the deployment process.</li>
                    <li>Integrated authentication and authorization with 3rd identity provider via OAuth2.0.</li>
                    <li>Developed a variety of data pipelines and web crawler for data searching, collection, parsing and normalization.</li>
                    <li>Developed functional AI agents using Python FastAPI, enabling advanced response synthesis and data correlation.</li>
                    <li>Engineered prompts and deployed multi-agent workflow for synthesising correct and related response of user's prompt.</li>
                    <li>Built deep search AI agent via LangChain and LangGraph with async event generators, real-time user prompt correction.</li>
                </ul>
            </div>
        </div>
        
        <div class="experience-item">
            <div class="job-header">
                <div>
                    <div class="job-title">Lead Cyber Security Consultant</div>
                    <div class="company">Wipro Shelde</div>
                </div>
                <div class="job-period">2022 May to 2023 May</div>
            </div>
            <div class="job-description">
                <ul class="responsibilities">
                    <li>Lead initiatives for migrating projects to AWS RDS and automating infrastructure and security baselines.</li>
                    <li>Designed and conducted proof of concept (POC) for integrating CyberArk Export Vault Data utility with AWS EC2.</li>
                    <li>Provided support for EY tech audits by demonstrating evidence of security controls.</li>
                    <li>Developed plugins for CyberArk Privileged Session Manager (PSM) and Central Policy Manager (CPM).</li>
                    <li>Designed and implemented Qualys vulnerability scanning solutions and processing report data using AWS Lambda.</li>
                    <li>Mentored junior team members to cultivate their skills in automation tools and security best practices.</li>
                </ul>
            </div>
        </div>
        
        <div class="experience-item">
            <div class="job-header">
                <div>
                    <div class="job-title">Cloud Security Engineer</div>
                    <div class="company">Pronto Software</div>
                </div>
                <div class="job-period">2018 Nov to 2022 April</div>
            </div>
            <div class="job-description">
                <ul class="responsibilities">
                    <li>Integrated and maintained Nagios as a cloud monitoring solution with emphasis on application-level checks.</li>
                    <li>Orchestrated responses to malicious security incidents, conducting thorough incident investigations.</li>
                    <li>Integrated VMWare LogInsight with AlienVault to automate the detection and alerting of security events.</li>
                    <li>Managed patch solutions for both Windows and RedHat environments.</li>
                    <li>Introduced Palo Alto Next-Generation Firewalls (NGFW) into the cloud infrastructure.</li>
                    <li>Defined and fine-tuning Palo Alto Intrusion Prevention System (IPS) detection policies.</li>
                    <li>Utilized containerization expertise to secure pronto ERP applications within Kubernetes clusters.</li>
                    <li>Conducted penetration testing for newly released web applications.</li>
                    <li>Managed vulnerability detection solutions and oversaw the remediation process.</li>
                    <li>Designed and configured CyberArk Privileged Access Management (PAM) solutions.</li>
                    <li>Collaborated with DevOps engineers to manage configuration management using Puppet modules.</li>
                </ul>
            </div>
        </div>
    </div>
    
    <div class="two-column">
        <div class="section">
            <h2 class="section-title">Education</h2>
            <div class="education-item">
                <div class="degree">Information and Network Security Master</div>
                <div class="school">University of Wollongong</div>
                <div class="education-period">2016-2018</div>
            </div>
            <div class="education-item">
                <div class="degree">Computer Science Bachelor</div>
                <div class="school">Shanghai Business School</div>
                <div class="education-period">2010-2014</div>
            </div>
        </div>
        
        <div class="section">
            <h2 class="section-title">Programming</h2>
            <div class="skill-item">
                <div class="skill-list">Python, Typescript, Fullstack, Bash</div>
            </div>
        </div>
    </div>
    
    <div class="section">
        <h2 class="section-title">Certificates</h2>
        <div class="certificate-item">Certified Ethical Hacker V10</div>
        <div class="certificate-item">AWS Certified Security Specialty</div>
        <div class="certificate-item">Cisco Certified Internet Expert – Routing and Switching CCIE #41400</div>
        <div class="certificate-item">RedHat Certified Architect - RHCA ID 140-048-935</div>
    </div>
    
    <div class="accent-line" style="margin-top: 30px;"></div>
</div>
"""

css_style = """
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    font-size: 12px;
    line-height: 1.3; /* 减小行高节省空间 */
    color: #333;
    background-color: #f8f9fa;
    padding: 15px; /* 减小内边距 */
    max-width: 1000px;
    margin: 0 auto;
}

.resume-container {
    background-color: white;
    box-shadow: 0 0 15px rgba(0, 0, 0, 0.1);
    border-radius: 8px;
    overflow: hidden;
    padding: 20px; /* 减小内边距 */
}

.header {
    border-bottom: 2px solid #2c3e50;
    padding-bottom: 15px; /* 减小内边距 */
    margin-bottom: 15px; /* 减小外边距 */
}

.name {
    font-size: 24px; /* 稍微减小字体大小 */
    font-weight: 700;
    color: #2c3e50;
    margin-bottom: 3px;
}

.title {
    font-size: 16px; /* 稍微减小字体大小 */
    color: #3498db;
    margin-bottom: 10px; /* 减小外边距 */
    font-weight: 600;
}

.contact-info {
    display: flex;
    flex-wrap: wrap;
    gap: 15px; /* 减小间距 */
    margin-bottom: 8px;
}

.contact-item {
    display: flex;
    align-items: center;
    font-size: 10px; /* 减小字体大小 */
}

.contact-item .icon {
    margin-right: 4px;
    color: #3498db;
}

.section {
    margin-bottom: 18px; /* 减小间距 */
    break-inside: auto; /* 使用更现代的break-inside属性 */
}

.section-title {
    font-size: 15px; /* 稍微减小字体大小 */
    color: #2c3e50;
    border-bottom: 1px solid #eee;
    padding-bottom: 6px; /* 减小内边距 */
    margin-bottom: 10px; /* 减小外边距 */
    font-weight: 700;
}

.about-me {
    background-color: #f8fafc;
    padding: 12px; /* 减小内边距 */
    border-left: 4px solid #3498db;
    margin-bottom: 15px; /* 减小外边距 */
    border-radius: 0 4px 4px 0;
    line-height: 1.4; /* 增加可读性 */
}

.experience-item {
    margin-bottom: 15px; /* 减小间距 */
    break-inside: auto; /* 允许分页 */
}

.job-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 6px; /* 减小间距 */
}

.job-title {
    font-weight: 700;
    font-size: 13px; /* 稍微减小字体大小 */
    color: #2c3e50;
}

.company {
    font-weight: 600;
    color: #555;
    font-size: 11px; /* 稍微减小字体大小 */
}

.job-period {
    font-weight: 600;
    color: #3498db;
    white-space: nowrap;
    font-size: 11px; /* 稍微减小字体大小 */
}

.job-description {
    margin-top: 5px; /* 减小间距 */
}

.responsibilities {
    list-style-type: none;
    padding-left: 0;
}

.responsibilities li {
    position: relative;
    padding-left: 12px; /* 减小缩进 */
    margin-bottom: 4px; /* 减小行间距 */
    font-size: 11px; /* 稍微减小字体大小 */
    line-height: 1.3; /* 调整行高 */
}

.responsibilities li:before {
    content: "•";
    position: absolute;
    left: 0;
    color: #3498db;
    font-weight: bold;
}

.two-column {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px; /* 减小间距 */
    margin-top: 5px;
}

.education-item, .skill-item {
    margin-bottom: 8px; /* 减小间距 */
}

.degree {
    font-weight: 700;
    color: #2c3e50;
    font-size: 12px; /* 调整字体大小 */
}

.school {
    font-weight: 600;
    color: #555;
    font-size: 11px; /* 调整字体大小 */
}

.education-period, .cert-date {
    color: #777;
    font-size: 10px; /* 减小字体大小 */
}

.skill-category {
    font-weight: 700;
    color: #2c3e50;
    margin-bottom: 3px;
}

.skill-list {
    color: #555;
    font-size: 11px; /* 调整字体大小 */
}

.certificate-item {
    margin-bottom: 6px; /* 减小间距 */
    padding-left: 12px; /* 减小缩进 */
    position: relative;
    font-size: 11px; /* 调整字体大小 */
}

.certificate-item:before {
    content: "✓";
    position: absolute;
    left: 0;
    color: #27ae60;
    font-weight: bold;
}

/* 优化分页控制 */
@media print {
    body {
        padding: 5px; /* 打印时更小的内边距 */
        background-color: white;
        margin: 0;
        font-size: 11px; /* 打印时更小的字体 */
    }
    
    .resume-container {
        box-shadow: none;
        border-radius: 0;
        padding: 15px; /* 打印时更小的内边距 */
        margin: 0;
    }
    
    /* 优化分页规则 */
    .section {
        break-inside: auto;
        margin-bottom: 10px;
    }
    
    /* 只在必要时避免分页 */
    .section-title {
        break-after: avoid;
    }
    
    /* 允许经验项目在页面中间分割 */
    .experience-item {
        break-inside: auto;
        page-break-inside: auto;
    }
    
    /* 确保单个职责项不被分割 */
    .responsibilities li {
        break-inside: avoid;
        page-break-inside: avoid;
    }
    
    /* 减小打印时的所有间距 */
    .header {
        padding-bottom: 10px;
        margin-bottom: 10px;
    }
    
    .about-me {
        padding: 10px;
        margin-bottom: 12px;
    }
    
    .experience-item {
        margin-bottom: 12px;
    }
}

.accent-line {
    height: 3px; /* 减小高度 */
    background: linear-gradient(90deg, #3498db, #2c3e50);
    margin-bottom: 15px; /* 减小间距 */
    border-radius: 2px;
}

.icon {
    display: inline-block;
    width: 10px; /* 减小宽度 */
    text-align: center;
    margin-right: 4px; /* 减小间距 */
    font-weight: bold;
    font-size: 10px; /* 减小字体大小 */
}

/* 为紧凑布局添加新类 */
.compact-list {
    margin-top: 3px;
}

.compact-list li {
    margin-bottom: 3px;
}
"""

generate_polished_pdf(html_body=html_body, css_styles=css_style)
