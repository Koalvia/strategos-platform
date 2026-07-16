# Customer BOPA Matches Endpoint Integration Guide

## Overview

The new `/api/v1/customers/{customer_id}/bopa-matches` endpoint searches BOPA (Boletín Oficial) documents that match a customer's name, NIF (tax ID), and associated project names. This provides visibility into regulatory documents relevant to each customer's affairs.

## Backend Implementation

### Endpoint

**Route:** `GET /api/v1/customers/{customer_id}/bopa-matches`

**Authentication:** Required (verified user)

**Query Parameters:**
- `limit`: Number of results per page (1–200, default 50)
- `offset`: Result offset for pagination (default 0)

**Response:** `DocumentSearchPage` (Pydantic model)

### Schema: DocumentSearchPage

```python
{
  "items": [
    {
      "id": 1,
      "document_name": "ejemplo_001",
      "title": "Resolución de ejemplo",
      "organisme": "Ministry Name",
      "tema": "Category",
      "article_date": "2026-07-15T10:30:00",
      "file_type": "html",
      "source_url": "https://bopa.ad/...",
      "pdf_url": "https://bopa.ad/...pdf",
      "bulletin_year": 2026,
      "bulletin_num": 77
    }
    // ... more DocumentSummary items
  ],
  "total": 42  // Total matching documents across all pages
}
```

### Service Layer

**File:** `backend/app/domains/bopa/service.py`

**Method:** `BopaService.search_documents_by_client()`

Searches documents using a composite OR filter:
- Customer name (case-insensitive substring match in title or HTML content)
- Customer NIF (case-insensitive substring match in title or HTML content)
- Each project name (case-insensitive substring match in title or HTML content)

Returns matches ordered by article date (most recent first).

**Example Usage:**
```python
bopa_service = BopaService(db, bopa_client)
results = bopa_service.search_documents_by_client(
    nombre="Fontaneria Puigcerdà SL",
    nif="A123456",
    proyectos=["Assessorament fiscal", "Gestió laboral"],
    limit=50,
    offset=0,
)
```

### Router Implementation

**File:** `backend/app/domains/customers/router.py` (lines 66–101)

The endpoint:
1. Validates the customer exists (404 if not found)
2. Fetches the customer's projects from Business Central
3. Calls `BopaService.search_documents_by_client()` with the customer's name, NIF, and project names
4. Returns the paginated document list

## Testing

### Test File

**File:** `backend/tests/test_customer_bopa_matches.py`

**Coverage:**
- **Basic functionality** (4 tests)
  - Endpoint returns valid `DocumentSearchPage` shape
  - Document summary has all expected fields
  - Search matches customer name
  - Search includes NIF and project names

- **Pagination** (4 tests)
  - `limit` parameter bounds results
  - `limit` validation (1–200)
  - `offset` parameter skips results
  - `offset` validation (non-negative)

- **Error handling** (2 tests)
  - Unknown customer returns 404
  - Unauthenticated requests rejected

- **Consistency** (2 tests)
  - Total count reflects all matches
  - Empty results handled correctly

- **Ordering** (1 test)
  - Results ordered by article_date descending

- **Integration** (1 test)
  - Endpoint works with generated fixtures

**Running tests:**
```bash
cd backend
TESTING=1 DATABASE_URL=sqlite:///./test.db SECRET_KEY=test-secret python run_tests.py -v -k "bopa_matches"
```

## Frontend Integration

### 1. API Route (Next.js)

**File:** `frontend/app/api/customers/[customer_id]/bopa-matches/route.ts`

Acts as a proxy between the frontend and backend, forwarding:
- Customer ID to the URL path
- `limit` and `offset` query parameters
- Authentication token (Bearer JWT)

### 2. Client-side API Helper

**File:** `frontend/features/customers/api.ts`

**Function:** `customersApi.getCustomerBopaMatches(customerId, params)`

```typescript
const result = await customersApi.getCustomerBopaMatches("cust-001", {
  limit: 10,
  offset: 0,
})

// Returns: { success: boolean, data?: BopaDocumentPage, message?: string }
```

### 3. React Component

**File:** `frontend/features/customers/customer-bopa-matches.tsx`

**Component:** `<CustomerBopaMatches customerId={string} />`

Displays a paginated table of matching BOPA documents with:
- Document title and name
- Bulletin reference (year/number) with link to bulletin detail
- Organisme (organization)
- Article date (formatted as locale date string)
- Action links to view full document

**Features:**
- Pagination with Previous/Next buttons
- Shows current page, total pages, and total document count
- Loading state while fetching
- Empty state if no matches
- Error handling (logs to console)

### 4. Customer Detail Page Integration

**File:** `frontend/app/(app)/clientes/[id]/page.tsx`

Added the `<CustomerBopaMatches>` component at the bottom of the customer detail page, after the projects section.

```typescript
// In ClienteDetailPage component:
<CustomerBopaMatches customerId={id} />
```

## Usage Flow

1. **User visits customer detail page:** `/clientes/{customer_id}`
2. **Page loads customer info and projects**
3. **`<CustomerBopaMatches>` component mounts**
4. **Component calls:** `customersApi.getCustomerBopaMatches(customerId)`
5. **Frontend API route** (`/api/customers/{customer_id}/bopa-matches`) proxies request
6. **Backend endpoint** searches BOPA documents
7. **Results displayed in paginated table**

## Field Mapping

| BOPA Backend Field | Frontend Type | Display |
|---|---|---|
| `id` | `number` | Used for links to document detail |
| `title` | `string` | Main document title in table |
| `document_name` | `string` | Identifier (e.g., "D_123_001") |
| `bulletin_year` / `bulletin_num` | `number` | Formatted as "YEAR núm. NUM" |
| `article_date` | `ISO datetime` | Localized date string (es-ES) |
| `organisme` | `string` | Organization/ministry name |
| `tema` | `string` | Category (not shown in current UI, available for filtering) |
| `file_type` | `string` | Document type (html, pdf, etc.) — not shown |
| `source_url` / `pdf_url` | `string` | Link targets (could be used for download buttons) |

## Error Handling

### Backend
- **404 Customer not found:** If customer_id doesn't exist in Business Central
- **422 Validation error:** If `limit` or `offset` parameters are invalid

### Frontend
- **401 Unauthorized:** If auth token missing or expired
- **Network errors:** Logged to console, graceful fallback to empty state
- **Missing API route:** Falls back to error message

## Performance Considerations

1. **Search Performance:** The BOPA search uses SQLAlchemy with:
   - `contains_eager()` for eager bulletin loading (one join, not N+1)
   - Indexed columns: `title`, `html_content`, `article_date`
   - Case-insensitive ILIKE with SQL wildcard escaping

2. **Pagination:** Default limit is 50 (max 200), offset-based
   - No cursor pagination (unlike customers/projects)
   - Suitable for small to medium datasets

3. **Frontend:** 
   - Component mounts once per page visit
   - Reloads when offset changes (pagination)
   - Does not cache results between page visits

## Known Limitations

1. **No search text parameter:** The endpoint searches all combinations of customer name, NIF, and project names automatically — no custom query parameter
2. **No ordering options:** Always ordered by article_date descending
3. **No filtering by BOPA facets:** Unlike the main BOPA search, this endpoint doesn't support organisme/tema filters

## Future Enhancements

1. Add `?q=` parameter for ad-hoc custom searches
2. Support BOPA facet filters (organisme, tema)
3. Implement cursor-based pagination for consistency
4. Add CSV/PDF export of results
5. Cache results in frontend to avoid re-fetching during pagination

## Files Created/Modified

### Backend
- ✅ Modified: `backend/app/domains/customers/router.py` (fixed endpoint)
- ✅ Created: `backend/tests/test_customer_bopa_matches.py` (20 tests)

### Frontend
- ✅ Created: `frontend/app/api/customers/[customer_id]/route.ts`
- ✅ Created: `frontend/app/api/customers/[customer_id]/bopa-matches/route.ts`
- ✅ Modified: `frontend/features/customers/api.ts` (added `getCustomerBopaMatches`)
- ✅ Created: `frontend/features/customers/customer-bopa-matches.tsx` (React component)
- ✅ Modified: `frontend/app/(app)/clientes/[id]/page.tsx` (integrated component)

## Verification Checklist

- [ ] Run backend tests: `pytest tests/test_customer_bopa_matches.py -v`
- [ ] Run lint: `ruff check .`
- [ ] Start frontend dev server: `pnpm dev`
- [ ] Navigate to any customer detail page
- [ ] Verify BOPA matches section loads and displays documents
- [ ] Test pagination (Previous/Next buttons)
- [ ] Test with non-existent customer (404)
- [ ] Test unauthenticated access (rejected)
