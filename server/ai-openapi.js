// OpenAPI 3.1 schema for GPT Actions: the 12 operations of /api/v2/ai (same operationIds and bodies as the old v2 API).
// GPT Actions limits: at most 30 operations, descriptions up to 300 characters, one security scheme.
const RESPONSES = {
  200: { description: 'Standard envelope', content: { 'application/json': { schema: { $ref: '#/components/schemas/AIResponse' } } } },
  default: { description: 'Error envelope (ok:false + code)', content: { 'application/json': { schema: { $ref: '#/components/schemas/AIError' } } } },
};

function op(operationId, summary, description, { params, body, tag = 'System' } = {}) {
  if (summary.length > 300 || description.length > 300) throw new Error(`OpenAPI text too long: ${operationId}`);
  const o = { operationId, summary, description, tags: [tag], responses: RESPONSES };
  if (params) o.parameters = params;
  if (body) o.requestBody = { required: true, content: { 'application/json': { schema: body } } };
  return o;
}

const param = (name, where, description, { required = false, type = 'string', dflt } = {}) =>
  ({ name, in: where, required, description, schema: { type, ...(dflt === undefined ? {} : { default: dflt }) } });

const ERROR_CODES = [
  'AUTH_REQUIRED', 'INVALID_API_KEY', 'API_KEY_DISABLED', 'INSUFFICIENT_SCOPE', 'AI_API_DISABLED', 'READ_ONLY_MODE', 'RATE_LIMITED', 'NOT_FOUND',
  'AMBIGUOUS_REFERENCE', 'VALIDATION_FAILED', 'MEDIA_VALIDATION_FAILED', 'PUBLICATION_BLOCKED', 'CRITICAL_ACTION_BLOCKED', 'APPROVAL_EXPIRED',
  'APPROVAL_INVALID', 'IDEMPOTENCY_CONFLICT', 'CONFLICT', 'UNKNOWN_CAPABILITY', 'BAD_REQUEST', 'INTERNAL_ERROR',
];

const EXECUTE_BODY = {
  type: 'object',
  required: ['action', 'parameters'],
  properties: {
    action: { type: 'string', description: 'Capability id exactly as returned by getCapabilities/getCapability (e.g. models.update, media.assign, models.publish).', example: 'models.update' },
    target: { type: ['string', 'null'], description: 'Target reference when the capability has one (model/category/article: id, slug or name). Omit otherwise. Ambiguous -> 409 AMBIGUOUS_REFERENCE with data.matches.' },
    parameters: {
      type: 'object',
      additionalProperties: true,
      description: 'Parameters of the capability. Copy ALL required ones using EXACTLY the names of parameters_schema from getCapability (see request_example). Never put them at the top level of the body.',
      properties: {
        nome: { type: 'string', description: 'e.g. models.create / categories.create: name to create' },
        changes: { type: 'object', additionalProperties: true, description: 'e.g. models.update / settings.update: only the fields to change' },
        fields: { type: 'object', additionalProperties: true, description: 'e.g. models.create: further form fields of the new draft' },
        url: { type: 'string', description: 'e.g. media.upload_url: public file URL / media.assign: uploaded path /api/uploads/...' },
        slot: { type: 'string', description: 'e.g. media.assign: foto_card, foto_copertina, public_photo_1, secret_video_1 ...' },
      },
      example: { changes: { badge: 'NUOVA' } },
    },
    parameters_json: { type: 'string', description: 'FALLBACK ONLY if `parameters` cannot be sent as an object: the same object as a JSON string, e.g. "{\\"nome\\": \\"Giulia Rossi\\"}". If both are present, `parameters` wins.' },
    dry_run: { type: 'boolean', default: false, description: 'true = preview only, nothing written (the only mode accepted in READ_ONLY). previewCapability forces it.' },
    reason: { type: 'string', description: 'Why (stored in the activity log)' },
    session_id: { type: 'string', description: 'Groups related changes so they can be undone together with rollback {session_id}. Reuse the one returned in data.session_id.' },
    expected_updated_at: { type: 'string', description: 'Optimistic concurrency: the etag/updated_at you last saw (409 CONFLICT if the target changed).' },
  },
  example: { action: 'models.update', target: 'Francesca', parameters: { changes: { badge: 'NUOVA' } }, dry_run: true, reason: 'anteprima del badge' },
};

function build(baseUrl, mode) {
  const P = '/api/v2/ai';
  const paths = {
    [`${P}/capabilities`]: { get: op('getCapabilities', 'List capabilities this key can run',
      'Compact catalogue: id, category, description, risk, target, parameters, access. Filter with category/q. Call first in a session.', {
        params: [param('category', 'query', 'models|media|categories|articles|settings|config|seo|system|rollback'), param('q', 'query', 'Free text filter'),
          param('compact', 'query', 'true (default) = short form', { type: 'boolean', dflt: true })],
        tag: 'Capabilities',
      }) },
    [`${P}/capabilities/{capability_id}`]: { get: op('getCapability', 'Capability detail',
      'parameters_schema, required_parameters, example_parameters and request_example (the exact previewCapability body), scopes, risk, access. Call it before preview/execute when the parameters are not already known.', {
        params: [param('capability_id', 'path', 'Capability id', { required: true })], tag: 'Capabilities',
      }) },
    [`${P}/preview`]: { post: op('previewCapability', 'Preview one capability (no write)',
      'Same validation as execute, dry_run forced, nothing written. Put the inputs INSIDE `parameters` with the exact names of parameters_schema; required fields must be there. Always preview before executing.',
      { body: EXECUTE_BODY, tag: 'Execute' }) },
    [`${P}/execute`]: { post: op('executeCapability', 'Execute one capability',
      'Same body as previewCapability. REVIEW_REQUIRED -> approval_required + approval.token: show before/after and ask the user, then approveApproval. READ_ONLY mode accepts only dry_run=true.',
      { body: EXECUTE_BODY, tag: 'Execute' }) },
    [`${P}/approvals`]: { get: op('listApprovals', 'Pending approvals', 'Your pending proposals (before/after, expiry). Tokens are never listed.', { tag: 'Approvals' }) },
    [`${P}/approvals/{approval_id}/approve`]: { post: op('approveApproval', 'Approve and apply a proposal',
      'Requires the token returned with approval_required (single use, expires). Blocked in READ_ONLY. Only after explicit user confirmation.', {
        params: [param('approval_id', 'path', 'Approval id', { required: true })],
        body: { type: 'object', required: ['token'], properties: { token: { type: 'string' }, reason: { type: 'string' } } }, tag: 'Approvals',
      }) },
    [`${P}/approvals/{approval_id}/reject`]: { post: op('rejectApproval', 'Reject a proposal', 'Nothing is changed.', {
      params: [param('approval_id', 'path', 'Approval id', { required: true })], body: { type: 'object', properties: { reason: { type: 'string' } } }, tag: 'Approvals',
    }) },
    [`${P}/jobs/{job_id}`]: { get: op('getJob', 'Async job status', 'This system runs every capability synchronously: there are no jobs, the answer is always NOT_FOUND.', {
      params: [param('job_id', 'path', 'Job id', { required: true })],
    }) },
    [`${P}/analytics/query`]: { post: op('queryAnalytics', 'Query analytics',
      'metric (visits, secret_opens, onlyfans_clicks, onlyfans_ctr, activation_rate ...), group_by (none, model, day), model, range (oggi, 7g, 30g, 90g). Always report sample_size, data_available, limitations.', {
        body: { type: 'object', properties: {
          metric: { type: 'string' }, group_by: { type: 'string' }, model: { type: 'string' }, range: { type: 'string', default: '30g' }, period: { type: 'string' },
          sort: { type: 'string' }, limit: { type: 'integer' }, question: { type: 'string' },
        } }, tag: 'Analytics',
      }) },
    [`${P}/status`]: { get: op('getSystemStatus', 'System status', 'Mode (READ_ONLY/FULL), base URL, content counts, registry counts, your permissions. Call when the user asks how the site is doing.') },
    [`${P}/rollback`]: { post: op('rollback', 'Undo changes',
      'version_id = one change; session_id = everything done in that session, newest first. dry_run:true shows the plan. Content edited afterwards is skipped, never overwritten.', {
        body: { type: 'object', properties: { version_id: { type: 'string' }, session_id: { type: 'string' }, dry_run: { type: 'boolean' }, reason: { type: 'string' } } }, tag: 'Rollback',
      }) },
    [`${P}/models/find`]: { post: op('findModel', 'Find a model',
      'Resolve id/slug/name/partial name (case- and accent-insensitive). 409 AMBIGUOUS_REFERENCE lists matches: show them, never pick one yourself. 404 NOT_FOUND: do not invent a profile.', {
        body: { type: 'object', required: ['reference'], properties: { reference: { type: 'string' } } }, tag: 'Models',
      }) },
  };
  return {
    openapi: '3.1.0',
    info: {
      title: 'LATO SEGRETO — Site Control API v2', version: '2.1.0',
      description: `12 universal operations: discover with getCapabilities, preview with previewCapability, apply with executeCapability. Server mode: ${mode}. `
        + 'Auth: API key as Bearer token. Never state that a change happened unless ok:true and rollback.version_ids is non-empty.',
    },
    servers: [{ url: baseUrl, description: 'LATO SEGRETO' }],
    paths,
    components: {
      securitySchemes: { ApiKeyBearer: { type: 'http', scheme: 'bearer', description: 'Dedicated AI key (ls_...) as Bearer token. Created in the admin: Impostazioni → Interfaccia AI.' } },
      schemas: {
        AIResponse: { type: 'object', properties: {
          ok: { type: 'boolean' }, action: { type: 'string' }, summary: { type: 'string' }, data: { type: 'object', additionalProperties: true },
          changes: { type: 'array', items: { type: 'object', additionalProperties: true } }, warnings: { type: 'array', items: { type: 'string' } },
          next_steps: { type: 'array', items: { type: 'string' } }, approval_required: { type: 'boolean' }, approval: { type: 'object', additionalProperties: true },
          rollback: { type: ['object', 'null'], additionalProperties: true }, request_id: { type: 'string' },
        } },
        AIError: { type: 'object', properties: {
          ok: { type: 'boolean' }, code: { type: 'string', enum: ERROR_CODES }, summary: { type: 'string' }, data: { type: 'object', additionalProperties: true },
          next_steps: { type: 'array', items: { type: 'string' } }, request_id: { type: 'string' },
        } },
      },
    },
    security: [{ ApiKeyBearer: [] }],
    tags: ['Capabilities', 'Execute', 'Approvals', 'Analytics', 'System', 'Rollback', 'Models'].map((name) => ({ name })),
  };
}

module.exports = { build };
