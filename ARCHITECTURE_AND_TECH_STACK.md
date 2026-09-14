# DSW Portal (Geeta University) — Comprehensive System Architecture & Tech Stack Documentation

---

## 1. Executive Overview

The **Dean of Student Welfare (DSW) Portal** for **Geeta University** is an enterprise-grade, full-stack digital governance and operational automation platform. It is engineered to digitize, streamline, and interconnect all student welfare activities, faculty task tracking, club operations, event governance, official university reporting, university webmail communications, grievance resolution, dynamic form collection, and gamified performance rankings.

### Core Objectives:
- **Role-Centric Governance**: Dedicated workspaces for **Super Admin (DSW Office)**, **Faculty Coordinators**, and **Students**.
- **Official Compliance & Reporting**: Automated generation of the standardized **Geeta University 7-Page Event Report** with budget reconciliations, geo-tagged photo matrices, and SDG mappings.
- **Workflow & Task Management**: Hierarchical task tracking with file proof submissions, deadline controls, and automated performance scoring.
- **Integrated Communications**: Per-user **Gmail API OAuth 2.0 integration** directly in the portal, plus targeted broadcast announcements.
- **AI-Powered Productivity**: Real-time English grammar, tone, and clarity refinement engine backed by Google Gemini Generative AI with offline heuristic failover.
- **Data Collection & Automation**: Drag-and-drop Dynamic Form builder with live **Google Sheets API / Webhook synchronization** and UPI QR code payment support.

---

## 2. High-Level System Architecture

The system follows a modern decoupled **Client-Server Architecture** with asynchronous REST APIs, a robust relational data layer, serverless/cloud deployment support, and multiple cloud service integrations.

```mermaid
graph TB
    subgraph ClientLayer ["Client Layer (Frontend - SPA)"]
        Browser["Modern Web Browsers / Mobile Viewports"]
        ReactApp["React 19 + TypeScript (Vite)"]
        Router["React Router v7 (Role-Guarded Routes)"]
        StateContext["Auth & Theme Contexts"]
        ApiDedupe["API Client + In-Flight Request Deduplicator"]
        UIComp["Tailwind CSS v4 + Lucide Icons + Recharts"]
    end

    subgraph APILayer ["Application & API Layer (Backend - FastAPI)"]
        UvicornASGI["FastAPI (Async ASGI / Mangum Adapter)"]
        AuthMiddleware["JWT Authentication & RBAC Guard"]
        SafeMigrations["Idempotent DB Migrations & Indexing Engine"]
        
        subgraph DomainRouters ["Domain Routers"]
            R_Auth["auth.py & users.py"]
            R_Tasks["tasks.py (Workflow Engine)"]
            R_Events["events.py & event_reports.py"]
            R_Clubs["clubs.py & committees.py & duty_charts.py"]
            R_Forms["forms.py & feedback.py"]
            R_LB["leaderboard_student.py & leaderboard_staff.py"]
            R_Email["email.py (Gmail OAuth & Mail Client)"]
            R_AI["ai.py (Gemini LLM Assistant)"]
            R_Misc["announcements.py, queries.py, dashboard.py, uploads.py"]
        end
    end

    subgraph ServiceLayer ["Core & Service Layer"]
        GmailService["Gmail Service (REST API v1 / MIME Builder)"]
        CryptoService["Email Crypto (HMAC-SHA256 Authenticated Encryption)"]
        SheetsService["Google Sheets Sync Service"]
        PDFService["Jinja2 7-Page Standard Report Engine"]
        AIService["Gemini AI Client (Multi-model Fallback + Cache)"]
    end

    subgraph DataLayer ["Data & Persistence Layer"]
        SQLAlchemyORM["SQLAlchemy 2.0 Async ORM"]
        AsyncPgDriver["asyncpg Driver (SSL + Supavisor Compat)"]
        PostgresDB[("PostgreSQL Database / Supabase")]
        LocalSQLite[("SQLite (aiosqlite - Local Dev)")]
    end

    subgraph ExternalServices ["External Cloud Services & APIs"]
        GoogleOAuth["Google Identity / OAuth 2.0"]
        GmailAPI["Google Gmail API (REST v1)"]
        GoogleSheets["Google Sheets API & Webhooks"]
        GeminiAPI["Google Gemini Generative Language API"]
        Storage["Static Storage / Vercel Blob / S3"]
    end

    %% Connections
    Browser --> ReactApp
    ReactApp --> Router
    Router --> StateContext
    StateContext --> ApiDedupe
    ApiDedupe -->|HTTPS / JSON REST API| UvicornASGI
    
    UvicornASGI --> AuthMiddleware
    AuthMiddleware --> DomainRouters
    
    DomainRouters --> ServiceLayer
    ServiceLayer --> GmailAPI
    ServiceLayer --> GoogleSheets
    ServiceLayer --> GeminiAPI
    R_Auth --> GoogleOAuth
    
    DomainRouters --> SQLAlchemyORM
    SQLAlchemyORM --> AsyncPgDriver
    AsyncPgDriver --> PostgresDB
    SQLAlchemyORM -.-> LocalSQLite
```

---

## 3. Detailed Technology Stack

### 3.1. Frontend Technology Stack (`dsw-front`)

| Technology / Library | Version | Category | Purpose / Description |
| :--- | :--- | :--- | :--- |
| **React** | `^19.2.7` | UI Framework | Core UI component library utilizing modern hooks, transitions, and concurrent rendering. |
| **TypeScript** | `~6.0.2` | Programming Language | Strict type-safety across models, API responses, form states, and component props. |
| **Vite** | `^8.1.1` | Build Tool & Dev Server | Ultra-fast HMR (Hot Module Replacement), optimized ESModule bundling, and tree-shaking. |
| **React Router DOM** | `^7.18.1` | Client-Side Routing | Declarative nested routing, role-based layout guarding (`allowedRoles`), and dynamic route parameters. |
| **Tailwind CSS** | `^4.3.3` | Styling Engine | Utility-first CSS framework with custom color tokens, dark mode variants, and responsive layouts. |
| **@tailwindcss/vite** | `^4.3.3` | Vite Integration | Native Tailwind v4 compiler integration for zero-config high-speed builds. |
| **Lucide React** | `^1.26.0` | Iconography | High-quality, modern SVG icon set for clean UI indicators. |
| **Recharts** | `^3.10.0` | Data Visualization | Composable SVG chart library for rendering analytics, category distributions, and performance trends. |
| **Canvas Confetti** | `^1.9.4` | Gamification UI | Particle celebration effects on task approvals, points awards, and podium highlights. |
| **Clsx & Tailwind-Merge** | `^2.1.1` / `^3.6.0` | Styling Utilities | Safe conditional class merging and conflict resolution for dynamic component styling. |
| **Oxlint** | `^1.71.0` | Code Quality | Blazing fast Rust-based linter for static code analysis. |

#### Frontend Architecture Highlights:
1. **Lazy Loading & Code Splitting**: All pages are dynamically imported via `React.lazy()` with a branded `PageLoader` fallback, keeping initial bundle size minimal.
2. **In-Flight Request Deduplication**: The `apiRequest()` utility in `src/lib/api.ts` maintains an active in-flight Promise map to eliminate duplicate simultaneous network calls during parallel component mounts.
3. **Theme & Auth Contexts**: Global React Context providers for JWT token management, persistent user state, and light/dark theme toggles.
4. **Adaptive Role Portals**: Dynamic sidebar navigation and dashboard widgets dynamically computed based on active role (`super_admin`, `faculty`, `student`).

---

### 3.2. Backend Technology Stack (`dsw-backend`)

| Technology / Library | Version | Category | Purpose / Description |
| :--- | :--- | :--- | :--- |
| **Python** | `3.10+ / 3.12+` | Programming Language | Core backend runtime. |
| **FastAPI** | `>=0.110.0` | Web Framework | Modern, high-performance asynchronous web framework based on ASGI and OpenAPI standards. |
| **Uvicorn** | `>=0.28.0` | ASGI Web Server | Lightning-fast asynchronous server for hosting FastAPI applications. |
| **Mangum** | `>=0.19.0` | Serverless Adapter | AWS Lambda and Vercel Serverless Function adapter for FastAPI. |
| **SQLAlchemy** | `>=2.0.28` | ORM & Query Builder | Modern 2.0 declarative async ORM with typed relationships, cascade deletes, and migrations. |
| **asyncpg** | `>=0.29.0` | PostgreSQL Driver | Highest-performance asynchronous driver for PostgreSQL with native SSL handling. |
| **aiosqlite** | `>=0.20.0` | SQLite Driver | Asynchronous SQLite driver for zero-dependency local development and unit tests. |
| **Pydantic & Pydantic-Settings** | `>=2.6.4` / `>=2.2.1` | Data Validation & Config | Strict schema validation, automatic JSON serialization, and `.env` configuration management. |
| **Python-Jose & Cryptography** | `>=3.3.0` | JWT & Cryptography | Encoding, decoding, and validating JSON Web Tokens (Access + Refresh tokens). |
| **Passlib & Bcrypt** | `>=1.7.4` / `>=4.0.0` | Password Hashing | Secure salted one-way hashing for user passwords. |
| **Jinja2** | `>=3.1.3` | Templating Engine | Dynamic rendering of official HTML/CSS print documents, 7-page event reports, and micro-task summaries. |
| **HTTPX** | `>=0.27.0` | Async HTTP Client | Asynchronous HTTP requests for external service communications. |
| **Python-Multipart** | `>=0.0.9` | Form Data Parser | Multipart/form-data support for direct file and proof uploads. |

---

### 3.3. External APIs & Cloud Integrations

| Integration | Protocol / Library | Implementation Details |
| :--- | :--- | :--- |
| **Google Gemini AI** | Google Generative Language REST API (`v1beta`) | Integrated in `app/routers/ai.py` with dynamic model failover (`gemini-flash-lite-latest` $\rightarrow$ `gemini-flash-latest` $\rightarrow$ `gemini-pro-latest`), exponential backoff retry, prompt SHA-256 caching (1-hour TTL), and an offline heuristic text polisher. |
| **Google Gmail API** | Google Workspace OAuth 2.0 & Gmail REST API | Implemented in `app/services/gmail_service.py` and `app/routers/email.py`. Provides per-user Google account linking, authenticated encrypted token storage, inbox listing, message threads, search, compose with attachments, reply, and label management. |
| **Google Sheets API & Webhooks** | Google REST API / Webhook Payload Delivery | Implemented in `app/services/google_sheets_service.py`. Automatically appends dynamic form submissions to configured Google Sheets. |
| **Authenticated Token Encryption** | Custom Cryptographic Engine (`email_crypto.py`) | HMAC-SHA256 authenticated encryption counter mode with random 16-byte IV and integrity verification (MAC) for OAuth refresh tokens. |
| **Supabase / PostgreSQL Pooler** | Supavisor on Port 6543 | Configured in `app/database.py` with `statement_cache_size=0`, SSL context override, and async connection pooling. |

---

## 4. Module & Feature Architecture

```
DSW Platform Feature Matrix
│
├── 1. Authentication & Security (RBAC)
│   ├── JWT Access Tokens (24h) & Refresh Tokens (7d)
│   ├── Bcrypt Salted Password Hashing
│   ├── Role Guards (Super Admin, Faculty, Student)
│   └── Forced First-Time Password Change Workflow
│
├── 2. Task & Workflow Management
│   ├── Standalone & Event-Linked Tasks
│   ├── Hierarchical Subtasks (Tree Structure)
│   ├── Priority Matrix (Low, Medium, High)
│   ├── Multi-Format Proof Submission (PDF, Docs, Images)
│   └── Multi-Stage Review (Pending, In Progress, Submitted, Approved, Declined)
│
├── 3. Event & Official Reporting Governance
│   ├── Event Lifecycle (Planned, Ongoing, Completed, Cancelled)
│   ├── Official 7-Page Standard Geeta University Report Generator
│   │   ├── Page 1: SDG Mapping & Identification
│   │   ├── Page 2: Approvals, Circulars, Posters, QR, Guests
│   │   ├── Page 3: Budget, Expenses, Minute-to-Minute, Participant Counts
│   │   ├── Page 4: Attendees List, Geo-tagged Photos, Winners, Handover
│   │   └── Page 5: Press Releases, Feedback, Digital Signatures
│   └── Printable HTML/CSS Micro-Reports
│
├── 4. Student Clubs & Core Committees
│   ├── Club Registration, KRA Objectives, & Custom Executive Roles Schema
│   ├── Club Member Rosters & Core Executive Tracking
│   ├── Club Bounty Tasks & Reward Points
│   ├── Club Leaderboard & Points Aggregation
│   ├── Core Event Committees (Faculty Mentor + Student Portfolios)
│   └── Event Duty Charts & Shift Rostering
│
├── 5. Dynamic Form Builder & Data Collection
│   ├── Custom Field Schema Builder (Text, Radio, Dropdown, Multi-select, Files)
│   ├── Dynamic UPI QR Code Generation & Payment Verification
│   ├── Live Google Sheets Sync / Webhook Dispatch
│   └── Public Shareable URL Slugs (`/forms/:slug`)
│
├── 6. Feedback & Grievance Resolution
│   ├── Dynamic Feedback Surveys (Anonymous or Identified)
│   ├── Grievance Ticket Matrix (Admin vs. Faculty Head Routing)
│   └── Resolution Lifecycle with Remarks & Closure Timestamps
│
├── 7. Dual Gamification & Leaderboard System
│   ├── Student Points Ledger (Task bounties, manual awards, tier ranks)
│   ├── Faculty Performance Scoring (+10 on-time approval, -3 decline/delay)
│   └── Dynamic Tier Classifications (Bronze, Silver, Gold, Platinum, Diamond)
│
├── 8. University Webmail Client
│   ├── Google OAuth 2.0 Account Connection
│   ├── Encrypted Refresh Token Storage
│   └── Webmail Interface (Inbox, Sent, Trash, Compose, Threads, Search)
│
└── 9. Gemini AI Assistant
    ├── One-Click Text Polishing across all long text fields
    ├── In-Memory Hash Cache & Offline Fallback Polisher
    └── Context-Aware Grammar and Tone Refinement
```

---

## 5. Database Schema & Data Models

The database comprises **15 core relational entities** managed via SQLAlchemy 2.0:

```mermaid
erDiagram
    users ||--o{ events : "creates / coordinates"
    users ||--o{ tasks : "assigns / assigned_to"
    users ||--o{ task_submissions : "submits / reviews"
    users ||--o{ announcements : "posts"
    users ||--o{ queries : "raises / closes"
    users ||--o{ clubs : "mentors / creates"
    users ||--o{ club_tasks : "submits / reviews"
    users ||--o{ dynamic_forms : "creates"
    users ||--o{ feedback_forms : "creates"
    users ||--o{ student_points_ledger : "receives / awards"
    users ||--o{ faculty_performance_ledger : "tracks"
    users ||--o| email_connections : "owns"
    
    events ||--o{ tasks : "contains"
    events ||--o{ event_reports : "documents"
    events ||--o{ duty_charts : "schedules"
    events ||--o{ core_committees : "organizes"
    
    tasks ||--o{ task_submissions : "has"
    tasks ||--o{ tasks : "parent_subtask"
    
    announcements ||--o{ announcement_reactions : "receives"
    
    clubs ||--o{ club_tasks : "issues"
    
    dynamic_forms ||--o{ dynamic_form_responses : "collects"
    
    feedback_forms ||--o{ feedback_questions : "contains"
    feedback_forms ||--o{ feedback_responses : "receives"
    feedback_responses ||--o{ feedback_answers : "contains"
```

### Key Data Entities:
1. **`users`**: Central identity model. Holds credentials, role (`super_admin`, `faculty`, `student`), department, designation, employee ID, roll number, course/branch, year, and active status.
2. **`events`**: Campus events with schedule, venue, status (`planned`, `ongoing`, `completed`, `cancelled`), and faculty coordinator.
3. **`tasks` & `task_submissions`**: Operational tasks with self-referential subtasks, due dates, priorities, and submitted proof artifacts (PDFs, docs, images, review notes).
4. **`event_reports`**: Comprehensive 7-page university event records holding SDG mappings, financials, photo metadata, participant counts, minute-to-minute agendas, and digital sign-offs.
5. **`clubs` & `club_tasks`**: Student societies with flexible JSON role schemas (`roles_schema`), student rosters, KRA statements, and point-earning club assignments.
6. **`core_committees` & `duty_charts`**: Event-specific duty assignments, venue shifts, and committee member roles.
7. **`dynamic_forms` & `dynamic_form_responses`**: Form definitions with JSON schemas, Google Sheet bindings, UPI payment configurations, and response payloads.
8. **`feedback_forms`, `feedback_questions`, `feedback_responses`, `feedback_answers`**: Survey engine supporting single/multi-choice questions and anonymous/authenticated responses.
9. **`leaderboard_tasks` & `leaderboard_task_submissions`**: Gamified student tasks with point values and submission verification.
10. **`student_points_ledger`**: Immutable audit ledger tracking all student point credits and debits.
11. **`faculty_performance_ledger`**: Automated scoring ledger for faculty members driven by task completion speed and approval outcomes.
12. **`announcements` & `announcement_reactions`**: Campus announcements with audience filtering (`faculty`, `students`, `both`) and emoji reactions.
13. **`queries`**: Grievance ticketing system with role-aware targeting (Admin vs. Faculty Head) and closure remarks.
14. **`notifications` & `audit_logs`**: System notifications and security audit trail.
15. **`email_connections`**: Per-user Google OAuth 2.0 Gmail token storage with HMAC-SHA256 encrypted refresh tokens.

---

## 6. Security, Reliability & Performance Design

### 6.1. Authentication & Cryptography
- **Stateless JWT Tokens**: Signed using `python-jose` with HS256. 24-hour expiration for access tokens, 7-day expiration for refresh tokens.
- **Bcrypt Password Storage**: Passwords hashed using industry-standard bcrypt with adaptive work factor.
- **Authenticated Refresh Token Encryption**: Gmail OAuth refresh tokens are encrypted using HMAC-SHA256 counter mode with random 16-byte initialization vectors and MAC integrity verification.
- **Role-Based Access Control (RBAC)**: All sensitive routes protected by FastAPI `Depends(require_role([...]))` and frontend route guards.

### 6.2. Database & Migration Reliability
- **Idempotent Safe Migrations**: The `apply_safe_migrations()` routine runs on server boot to automatically verify and add missing columns and performance indexes without dropping data.
- **High-Performance Query Indexing**: Dedicated indexes created on foreign keys, status flags, role filters, target IDs, and chronological sort keys (`created_at DESC`).
- **Supabase / Supavisor Compatibility**: Fully configured for transaction poolers (Port 6543) by explicitly setting `statement_cache_size=0` in asyncpg to prevent prepared statement collisions.

### 6.3. In-Memory TTL Caching & Real-Time Query Profiling
- **Request Profiling Middleware**: Measures total response time, query count, and cumulative DB query time attached to response headers (`X-Process-Time`, `X-DB-Queries`, `X-DB-Time`).
- **TTL Cache Layer (`app/core/cache.py`)**: High-speed in-memory cache for expensive `SUM()` / `COUNT()` aggregations on Dashboard summaries, student rankings, staff rankings, and club leaderboards with automatic write invalidation.
- **Image Optimization Engine**: Automatic resizing and compression of uploaded event report photos and proof documents using Pillow to eliminate high bandwidth payloads.

### 6.4. AI Resilience & Graceful Degradation
- **Multi-Model Fallback**: Cascade through `gemini-flash-lite-latest` $\rightarrow$ `gemini-flash-latest` $\rightarrow$ `gemini-pro-latest`.
- **In-Memory Hash Caching**: SHA-256 prompt hashing stores recent AI completions in an LRU memory cache with a 1-hour TTL.
- **Offline Polisher Fallback**: If network or API quota issues arise, a deterministic regex/rule-based offline polisher executes automatically.

---

## 7. Directory Structure

```
DSW/
├── dsw-backend/                    # FastAPI Async Backend Application
│   ├── app/
│   │   ├── core/                   # Security, dependencies, scoring rules, cache, logos
│   │   │   ├── cache.py            # High-speed in-memory TTL caching engine
│   │   │   ├── deps.py             # Auth dependencies & RBAC
│   │   │   ├── logo_base64.py      # Embedded university branding assets
│   │   │   ├── scoring_rules.py    # Points and scoring logic
│   │   │   └── security.py         # Password hashing & JWT generation
│   │   ├── models/
│   │   │   └── all_models.py       # Complete SQLAlchemy 2.0 Async ORM models
│   │   ├── routers/                # Domain-specific API route handlers
│   │   │   ├── ai.py               # Gemini AI text enhancement
│   │   │   ├── announcements.py    # Broadcast notices & reactions
│   │   │   ├── auth.py             # Login, token refresh, password resets
│   │   │   ├── clubs.py            # Student clubs & society tasks
│   │   │   ├── committees.py       # Core festival/event committees
│   │   │   ├── dashboard.py        # Aggregate metrics & statistics
│   │   │   ├── duty_charts.py      # Staff & student event rosters
│   │   │   ├── email.py            # Gmail OAuth & Webmail endpoints
│   │   │   ├── event_reports.py    # Official 7-page PDF report engine
│   │   │   ├── events.py           # Event lifecycle management
│   │   │   ├── feedback.py         # Feedback surveys & analytics
│   │   │   ├── forms.py            # Dynamic forms & Google Sheets sync
│   │   │   ├── leaderboard_staff.py# Faculty performance score ledger
│   │   │   ├── leaderboard_student.py # Student points & task bounties
│   │   │   ├── notifications.py    # In-app notifications
│   │   │   ├── queries.py          # Grievance ticket handling
│   │   │   ├── tasks.py            # Task assignment & proof review
│   │   │   ├── uploads.py          # File upload & static serving
│   │   │   └── users.py            # User management & profile updates
│   │   ├── schemas/
│   │   │   └── schemas.py          # Pydantic v2 request & response schemas
│   │   ├── services/               # Specialized business logic services
│   │   │   ├── email_crypto.py     # HMAC-SHA256 authenticated encryption
│   │   │   ├── gmail_service.py    # Google Gmail API v1 integration
│   │   │   ├── google_sheets_service.py # Google Sheets auto-sync
│   │   │   ├── notification_service.py # System notification dispatcher
│   │   │   └── pdf_report_service.py # Jinja2 HTML report templates
│   │   ├── config.py               # Pydantic settings & environment configs
│   │   ├── database.py             # Async database session & engine factory
│   │   └── main.py                 # FastAPI application root & lifecycle
│   ├── requirements.txt            # Python package dependencies
│   └── vercel.json                 # Vercel serverless build & route config
│
└── dsw-front/                      # React 19 + TypeScript Frontend Application
    ├── src/
    │   ├── components/
    │   │   ├── common/             # Reusable UI (ImproveEnglishButton, ThemeToggle)
    │   │   ├── events/             # FileUploadField, Event widgets
    │   │   ├── layout/             # AppLayout, Navbar, Sidebar
    │   │   ├── mail/               # MailComposeModal, MailSetupScreen
    │   │   ├── notifications/      # NotificationModal
    │   │   └── tasks/              # ProofViewer, TaskProofSubmitter
    │   ├── context/
    │   │   ├── AuthContext.tsx     # Authentication state & login methods
    │   │   └── ThemeContext.tsx    # Light / Dark mode state management
    │   ├── lib/
    │   │   └── api.ts              # Fetch wrapper & in-flight deduplicator
    │   ├── pages/
    │   │   ├── admin/              # Super Admin pages (Tasks, Faculty, Forms, Reports)
    │   │   ├── faculty/            # Faculty Workstation (MyTasks, Reports)
    │   │   ├── student/            # Student Portal (Dashboard, Bounties)
    │   │   ├── public/             # LandingPage, PublicDynamicForm, PublicFeedback
    │   │   ├── shared/             # ClubsPage, MailPage, EventReportFormPage, etc.
    │   │   └── LoginPage.tsx       # Unified / Role-specific login portal
    │   ├── App.tsx                 # Route declarations & lazy-loading registry
    │   ├── main.tsx                # DOM entry point
    │   └── index.css               # Tailwind CSS v4 design tokens & base styles
    ├── package.json                # Node dependencies & build scripts
    ├── tsconfig.json               # TypeScript compiler options
    └── vite.config.ts              # Vite plugins & build configuration
```

---

## 8. Deployment & Environment Configuration

### Backend Environment Variables (`dsw-backend/.env`)
```bash
PROJECT_NAME="DSW Geeta University Portal API"
ENV="production"
DATABASE_URL="postgresql+asyncpg://user:password@host:6543/postgres"
JWT_SECRET="geeta-university-dsw-super-secret-key-2026"
JWT_REFRESH_SECRET="geeta-university-dsw-refresh-secret-key-2026"
ACCESS_TOKEN_EXPIRE_MINUTES=1440
REFRESH_TOKEN_EXPIRE_DAYS=7
UPLOAD_DIR="/tmp/uploads"

# Google Gemini AI Key
GEMINI_API_KEY="your-gemini-api-key"

# Google Workspace OAuth 2.0 for Webmail
GOOGLE_CLIENT_ID="your-google-client-id.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET="your-google-client-secret"
GOOGLE_OAUTH_REDIRECT_URI="https://your-api-domain.com/api/email/oauth/callback"
FRONTEND_URL="https://your-frontend-domain.com"
MAIL_ENCRYPTION_SECRET="gu-dsw-mail-encryption-key-2026-secret"
```

### Frontend Environment Variables (`dsw-front/.env`)
```bash
VITE_API_BASE_URL="https://your-api-domain.com/api"
```

---

*Document compiled for Geeta University — Dean of Student Welfare (DSW) Portal.*
