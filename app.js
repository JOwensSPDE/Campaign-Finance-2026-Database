const state = {
  data: [],
  outside: { groups: [], allocations: [], reviewIssues: [] },
  race: 'all',
  donorLimit: 50,
  donorSort: { key: 'amount', direction: 'desc' }
};
const money = value => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value || 0);
const exactMoney = value => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value || 0);
const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const normalize = value => String(value ?? '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

async function init() {
  try {
    const [response, outsideResponse] = await Promise.all([
      fetch('data/campaign-finance.json?v=24'), fetch('data/outside-spending.json?v=24')
    ]);
    if (!response.ok || !outsideResponse.ok) throw new Error(`Data request failed`);
    const [payload, outside] = await Promise.all([response.json(), outsideResponse.json()]);
    state.data = payload.candidates;
    state.outside = outside;
    populateRaceFilter();
    bindEvents();
    route();
  } catch (error) {
    document.querySelector('#candidate-grid').innerHTML = `<div class="empty"><strong>Could not load the campaign data.</strong><br>Run this site through a web server rather than opening index.html directly.</div>`;
    console.error(error);
  }
}

function bindEvents() {
  const search = document.querySelector('#site-search');
  search.addEventListener('input', () => renderSearch(search.value));
  search.addEventListener('keydown', event => { if (event.key === 'Escape') clearSearch(); });
  document.querySelector('#clear-search').addEventListener('click', clearSearch);
  document.querySelector('#race-filter').addEventListener('change', event => {
    state.race = event.target.value;
    renderOverview();
  });
  window.addEventListener('hashchange', route);
  document.addEventListener('click', event => {
    if (!event.target.closest('.search-shell') && !event.target.closest('#search-results')) {
      document.querySelector('#search-results').hidden = true;
    }
  });
}

function populateRaceFilter() {
  const races = [...new Map(state.data.map(c => [c.raceId, c.race])).entries()]
    .sort((a, b) => a[1].localeCompare(b[1], undefined, { numeric: true }));
  document.querySelector('#race-filter').insertAdjacentHTML('beforeend', races.map(([id, name]) => `<option value="${esc(id)}">${esc(name)}</option>`).join(''));
}

function route() {
  const match = location.hash.match(/^#candidate\/(.+)$/);
  if (match) {
    const candidate = state.data.find(c => c.id === decodeURIComponent(match[1]));
    if (candidate) return renderCandidate(candidate);
  }
  const advertiserMatch = location.hash.match(/^#advertiser\/(.+)$/);
  if (advertiserMatch) {
    const group = state.outside.groups.find(g => g.account === decodeURIComponent(advertiserMatch[1]));
    if (group) return renderAdvertiser(group);
  }
  renderOverview();
}

function renderOverview() {
  document.querySelector('#overview').hidden = false;
  document.querySelector('#candidate-view').hidden = true;
  document.querySelector('#advertiser-view').hidden = true;
  const list = state.race === 'all'
    ? [...state.data].sort((a, b) => b.totalReceipts - a.totalReceipts || a.candidate.localeCompare(b.candidate))
    : state.data.filter(c => c.raceId === state.race);
  const races = new Set(list.map(c => c.raceId)).size;
  const raised = list.reduce((sum, c) => sum + c.totalReceipts, 0);
  const visibleIds = new Set(list.map(c => c.id));
  const outside = state.outside.allocations.filter(a => visibleIds.has(a.candidateId) && a.allocationType !== 'direct-pac-contribution').reduce((sum, a) => sum + a.amount, 0);
  document.querySelector('#summary-stats').innerHTML = `
    <div class="stat"><strong>${list.length}</strong><span>Candidates</span></div>
    <div class="stat"><strong>${races}</strong><span>Contested races</span></div>
    <div class="stat"><strong>${money(raised)}</strong><span>Direct Candidate Donations</span></div>
    <div class="stat outside-stat"><strong>${money(outside)}</strong><span>Additional Outside Spending Tied To Candidates</span></div>`;
  document.querySelector('#candidate-grid').innerHTML = list.length ? list.map(candidateCard).join('') : '<div class="empty">No candidates match this filter.</div>';
  renderOutsideOverview(list);
  document.querySelectorAll('.candidate-card').forEach(card => {
    const open = () => { location.hash = `candidate/${card.dataset.id}`; };
    card.addEventListener('click', open);
    card.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); }
    });
  });
}

function candidateCard(c) {
  const outside = outsideTotal(c.id);
  const undetermined = hasUndeterminedSupport(c.id);
  const outsideDisplay = outside ? `${money(outside)}${undetermined ? '*' : ''}` : 'Undetermined';
  return `<article class="candidate-card" data-id="${esc(c.id)}" tabindex="0" aria-label="View ${esc(c.candidate)}">
    <div class="race-tag">${esc(c.race)}</div>
    <h3>${esc(c.candidate)}</h3>
    <div class="committee">${esc(c.committee)}</div>
    <div class="money-row"><div><span>Direct Candidate Donations</span><strong>${money(c.totalReceipts)}</strong></div><button class="card-button" tabindex="-1">View →</button></div>
    ${outside || undetermined ? `<div class="outside-card-amount"><span>Additional Outside Spending Tied To Candidate</span><strong>${outsideDisplay}</strong></div>` : ''}
  </article>`;
}

function outsideForCandidate(candidateId) {
  return state.outside.allocations.filter(item => item.candidateId === candidateId && item.allocationType !== 'direct-pac-contribution');
}

function outsideTotal(candidateId) {
  return outsideForCandidate(candidateId).reduce((sum, item) => sum + item.amount, 0);
}

function hasUndeterminedSupport(candidateId) {
  return state.outside.groups.some(group => (group.unallocatedCandidateSupport || []).includes(candidateId));
}

function renderOutsideOverview(visibleCandidates) {
  const ids = new Set(visibleCandidates.map(c => c.id));
  const allocations = state.outside.allocations.filter(a => ids.has(a.candidateId));
  const accounts = new Set(allocations.map(a => a.account));
  const groups = (state.race === 'all' ? state.outside.groups : state.outside.groups.filter(g => accounts.has(g.account)))
    .filter(g => g.reportedExpenditures > 0)
    .sort((a,b) => b.reportedExpenditures - a.reportedExpenditures);
  const container = document.querySelector('#outside-overview');
  container.innerHTML = `<div class="section-heading outside-heading"><div><div class="eyebrow">Independent activity and PACs</div><h2>Outside advertisers and PACs</h2><p>Third-party advertiser spending remains separate from candidate fundraising. PAC profiles identify direct candidate donations without adding them again to outside-spending totals.</p></div></div>
    <div class="advertiser-grid">${groups.map(group => `<a class="advertiser-card" href="#advertiser/${encodeURIComponent(group.account)}"><div class="race-tag">${esc(group.entityType || 'Third-party advertiser')}</div><h3>${esc(group.organization)}</h3><div class="advertiser-metrics"><div><span>Total reported expenditures</span><strong>${money(group.reportedExpenditures)}</strong></div><div><span>${group.entityType === 'PAC' ? 'Direct candidate donations identified' : 'Tied to candidates shown'}</span><strong>${money(group.candidateAttributed)}</strong></div></div><span class="profile-link">View ${group.entityType === 'PAC' ? 'PAC' : 'advertiser'} profile →</span></a>`).join('') || '<div class="empty">No outside advertisers or PACs match this filter.</div>'}</div>`;
}

function renderSearch(query) {
  const results = document.querySelector('#search-results');
  const clear = document.querySelector('#clear-search');
  const q = normalize(query.trim());
  clear.style.display = q ? 'block' : 'none';
  if (q.length < 2) { results.hidden = true; return; }
  const candidates = state.data.filter(c => normalize(`${c.candidate} ${c.committee} ${c.race}`).includes(q)).slice(0, 8);
  const groups = state.outside.groups.filter(g => normalize(g.organization).includes(q)).slice(0, 6);
  const donors = [];
  for (const candidate of state.data) {
    for (const donor of candidate.donors) {
      if (normalize(`${donor.name} ${donor.address}`).includes(q)) donors.push({ ...donor, candidate });
    }
  }
  donors.sort((a, b) => b.amount - a.amount);
  let html = '';
  if (candidates.length) html += `<div class="search-group-title">Candidates</div>${candidates.map(c => `<button class="search-item" data-candidate="${esc(c.id)}"><strong>${esc(c.candidate)}</strong><span>${esc(c.race)}</span></button>`).join('')}`;
  if (groups.length) html += `<div class="search-group-title">Outside advertisers and PACs</div>${groups.map(g => `<button class="search-item" data-group="${esc(g.account)}"><strong>${esc(g.organization)}</strong><span>${esc(g.entityType || 'Third-party advertiser')} · ${money(g.reportedExpenditures)} reported</span></button>`).join('')}`;
  if (donors.length) html += `<div class="search-group-title">Contributions ${donors.length > 12 ? `(top 12 of ${donors.length.toLocaleString()})` : ''}</div>${donors.slice(0, 12).map(d => `<button class="search-item" data-candidate="${esc(d.candidate.id)}" data-donor="${esc(d.name)}"><strong>${esc(d.name)}</strong><span>${money(d.amount)} to ${esc(d.candidate.candidate)}</span></button>`).join('')}`;
  results.innerHTML = html || '<div class="empty">No matching donors or candidates.</div>';
  results.hidden = false;
  results.querySelectorAll('[data-candidate]').forEach(button => button.addEventListener('click', () => {
    state.pendingDonor = button.dataset.donor || '';
    clearSearch();
    location.hash = `candidate/${button.dataset.candidate}`;
  }));
  results.querySelectorAll('[data-group]').forEach(button => button.addEventListener('click', () => {
    clearSearch();
    location.hash = `advertiser/${encodeURIComponent(button.dataset.group)}`;
  }));
}

function clearSearch() {
  document.querySelector('#site-search').value = '';
  document.querySelector('#clear-search').style.display = 'none';
  document.querySelector('#search-results').hidden = true;
}

function renderCandidate(c) {
  document.querySelector('#overview').hidden = true;
  document.querySelector('#advertiser-view').hidden = true;
  const view = document.querySelector('#candidate-view');
  view.hidden = false;
  state.donorLimit = 50;
  state.donorSort = { key: 'amount', direction: 'desc' };
  const rivals = state.data.filter(x => x.raceId === c.raceId).sort((a,b) => b.totalReceipts - a.totalReceipts);
  const max = Math.max(...rivals.map(x => x.totalReceipts), 1);
  const outsideEntries = outsideForCandidate(c.id).sort((a,b) => new Date(b.date) - new Date(a.date));
  const unallocatedSupport = state.outside.groups.filter(group => (group.unallocatedCandidateSupport || []).includes(c.id));
  const candidateOutside = outsideEntries.reduce((sum, item) => sum + item.amount, 0);
  const candidateOutsideDisplay = candidateOutside
    ? `${exactMoney(candidateOutside)}${unallocatedSupport.length ? '*' : ''}`
    : unallocatedSupport.length ? 'Undetermined' : exactMoney(0);
  const outsideMax = Math.max(...rivals.map(x => outsideTotal(x.id)), 1);
  const known = c.delawareTotal + c.outsideTotal;
  const circumference = 2 * Math.PI * 70;
  const deShare = known ? c.delawareTotal / known : 0;
  const outShare = known ? c.outsideTotal / known : 0;
  view.innerHTML = `
    <button class="back-button" id="back-overview">← All candidates</button>
    <div class="candidate-header"><div class="eyebrow">${esc(c.race)}</div><h1>${esc(c.candidate)}</h1><p>${esc(c.committee)} · Data through ${esc(c.periodEnd)}</p></div>
    <div class="metric-grid five">
      <div class="metric"><span>Total receipts</span><strong>${exactMoney(c.totalReceipts)}</strong>${c.annual2025Receipts !== undefined ? `<small>2025: ${exactMoney(c.annual2025Receipts)} · 2026: ${exactMoney(c.current2026Receipts)}</small>` : '<small>Available 2026 reports only</small>'}</div>
      <div class="metric"><span>Candidate loans</span><strong>${exactMoney(c.candidateLoans)}</strong><small>Schedule D-1 loans from the candidate</small></div>
      <div class="metric"><span>Total expenditures</span><strong>${exactMoney(c.totalExpenditures)}</strong></div>
      <div class="metric"><span>Ending balance</span><strong>${exactMoney(c.endingBalance)}</strong></div>
      <div class="metric outside-metric"><span>Additional Outside Spending Tied To Candidate</span><strong>${candidateOutsideDisplay}</strong>${unallocatedSupport.length ? '<small>* Additional support was reported without a candidate-level dollar amount.</small>' : ''}</div>
    </div>
    <div class="charts">
      <article class="chart-card"><h3>Where itemized money came from</h3><p class="chart-deck">Based on the mailing addresses reported for Schedule A contributions.</p>
        <div class="donut-wrap">
          <svg class="donut" viewBox="0 0 180 180" role="img" aria-label="${Math.round(deShare*100)} percent Delaware, ${Math.round(outShare*100)} percent outside Delaware">
            <circle class="base" cx="90" cy="90" r="70"/>
            <circle cx="90" cy="90" r="70" stroke="var(--blue)" stroke-dasharray="${deShare*circumference} ${circumference}"/>
            <circle cx="90" cy="90" r="70" stroke="var(--orange)" stroke-dasharray="${outShare*circumference} ${circumference}" stroke-dashoffset="${-deShare*circumference}"/>
          </svg>
          <div class="legend">
            ${legendRow('var(--blue)', 'Delaware addresses', c.delawareTotal, deShare)}
            ${legendRow('var(--orange)', 'Outside Delaware', c.outsideTotal, outShare)}
            ${c.unitemizedOrOther > .01 ? legendRow('#b6b4ad', 'Not itemized / other receipts', c.unitemizedOrOther, c.totalReceipts ? c.unitemizedOrOther/c.totalReceipts : 0) : ''}
          </div>
        </div>
      </article>
      <article class="chart-card"><h3>Fundraising in this race</h3><p class="chart-deck">Total Schedule A receipts reported by each candidate.</p>
        ${rivals.map(r => `<div class="bar-row"><div class="bar-label" title="${esc(r.candidate)}">${esc(r.candidate)}</div><div class="bar-track"><div class="bar-fill ${r.id===c.id?'selected':''}" style="width:${Math.max(2,r.totalReceipts/max*100)}%"></div><span class="bar-value">${money(r.totalReceipts)}</span></div></div>`).join('')}
      </article>
      <article class="chart-card outside-chart"><h3>Outside Spending In This Race</h3><p class="chart-deck">Candidate-associated spending by third-party advertisers, shown separately from candidate fundraising.</p>
        ${rivals.map(r => { const amount = outsideTotal(r.id); const undetermined = hasUndeterminedSupport(r.id); const display = `${money(amount)}${undetermined ? ' + Additional Undetermined Support' : ''}`; return `<div class="bar-row"><div class="bar-label" title="${esc(r.candidate)}">${esc(r.candidate)}</div><div class="bar-track"><div class="bar-fill outside ${r.id===c.id?'selected':''}" style="width:${amount ? Math.max(2,amount/outsideMax*100) : 0}%"></div><span class="bar-value${undetermined ? ' undetermined-support' : ''}">${display}</span></div></div>`; }).join('')}
      </article>
    </div>
    ${outsideEntries.length ? `<section class="outside-section"><div><h3>Outside spending tied to ${esc(c.candidate)}</h3><p class="chart-deck">This is not money received or controlled by the candidate’s committee.</p></div><div class="table-wrap"><table><thead><tr><th>Advertiser</th><th>Activity</th><th>How attributed</th><th>Date</th><th>Amount</th></tr></thead><tbody>${outsideEntries.map(item => `<tr><td><strong>${esc(item.organization)}</strong></td><td>${esc(item.activity)}${item.note?.includes('does not reconcile') ? '<small class="row-note">Filing allocation discrepancy</small>' : ''}</td><td>${outsidePosition(item)}</td><td>${esc(item.date)}</td><td>${exactMoney(item.amount)}</td></tr>`).join('')}</tbody></table></div></section>` : ''}
    ${unallocatedSupport.length ? `<section class="outside-section"><div><h3>Additional reported support with no candidate total</h3><p class="chart-deck">These advertisers identify ${esc(c.candidate)} as supported but do not report an amount attributable to this candidate. Nothing from these filings is added to the candidate’s outside-spending total.</p></div><div class="advertiser-candidate-grid">${unallocatedSupport.map(group => `<a class="advertiser-candidate-card" href="#advertiser/${encodeURIComponent(group.account)}"><div><div class="race-tag">${esc(group.entityType || 'Third-party advertiser')}</div><h4>${esc(group.organization)}</h4><div class="position-list"><span class="position support">Support</span></div></div><strong>Amount unavailable</strong></a>`).join('')}</div></section>` : ''}
    <section class="donor-section"><div class="donor-tools"><div><h3>Reported contributions</h3><p class="chart-deck" id="donor-count"></p></div><label><span class="sr-only">Filter this candidate's contributors</span><input id="donor-filter" type="search" placeholder="Filter these contributions…" value="${esc(state.pendingDonor || '')}"></label></div><div id="donor-table"></div></section>`;
  state.pendingDonor = '';
  document.querySelector('#back-overview').addEventListener('click', () => { location.hash = ''; });
  const filter = document.querySelector('#donor-filter');
  filter.addEventListener('input', () => { state.donorLimit = 50; renderDonorTable(c, filter.value); });
  renderDonorTable(c, filter.value);
  window.scrollTo({ top: document.querySelector('#candidate-view').offsetTop - 15, behavior: 'smooth' });
}

function renderAdvertiser(group) {
  document.querySelector('#overview').hidden = true;
  document.querySelector('#candidate-view').hidden = true;
  const view = document.querySelector('#advertiser-view');
  view.hidden = false;
  const entries = state.outside.allocations
    .filter(item => item.account === group.account)
    .sort((a, b) => new Date(b.date) - new Date(a.date) || b.amount - a.amount);
  const byCandidate = new Map();
  entries.forEach(item => {
    const candidate = state.data.find(c => c.id === item.candidateId);
    const key = candidate?.id || `reported-${item.candidateName}`;
    const record = byCandidate.get(key) || { candidate, candidateName: item.candidateName, amount: 0, entries: [] };
    record.amount += item.amount;
    record.entries.push(item);
    byCandidate.set(key, record);
  });
  (group.unallocatedCandidateSupport || []).forEach(candidateId => {
    if (byCandidate.has(candidateId)) return;
    const candidate = state.data.find(c => c.id === candidateId);
    byCandidate.set(candidateId, { candidate, candidateName: '', amount: 0, entries: [], unallocated: true });
  });
  const candidateTotals = [...byCandidate.values()]
    .sort((a, b) => b.amount - a.amount || profileCandidateName(a).localeCompare(profileCandidateName(b)));
  const isPac = group.entityType === 'PAC';
  view.innerHTML = `
    <button class="back-button" id="back-advertisers">← All outside advertisers and PACs</button>
    <div class="candidate-header advertiser-header"><div class="eyebrow">${esc(group.entityType || 'Third-party advertiser')}</div><h1>${esc(group.organization)}</h1><p>${isPac ? 'PAC expenditures, including identified direct candidate donations' : 'Independent spending reported separately from candidate fundraising'}</p></div>
    <div class="metric-grid four">
      <div class="metric"><span>Total reported expenditures</span><strong>${exactMoney(group.reportedExpenditures)}</strong></div>
      <div class="metric outside-metric"><span>${isPac ? 'Direct candidate donations identified' : 'Attributed to candidates'}</span><strong>${exactMoney(group.candidateAttributed)}</strong></div>
      <div class="metric"><span>Candidates associated</span><strong>${candidateTotals.length.toLocaleString()}</strong></div>
      <div class="metric"><span>Reports included</span><strong>${group.reportCount.toLocaleString()}</strong></div>
    </div>
    <section class="outside-section advertiser-candidates"><div><h3>${isPac ? 'Candidates receiving direct PAC donations' : 'Candidates tied to this advertiser’s spending'}</h3><p class="chart-deck">${group.unallocatedSupportNote ? esc(group.unallocatedSupportNote) + ' No portion is added to an individual candidate’s outside-spending total.' : isPac ? 'These are PAC expenditures paid to named candidate committees. They are not added to Additional Outside Spending totals because candidate committees may also report them as direct donations.' : 'These amounts are not contributions to candidate committees. Opposition spending is credited to the candidate who benefits.'}</p></div>
      <div class="advertiser-candidate-grid">${candidateTotals.map(profileCandidateCard).join('') || `<div class="empty">${isPac ? 'This PAC reported spending, but the supplied filing does not identify a direct donation to a candidate committee.' : 'The supplied filings do not provide a defensible allocation to an individual candidate.'}</div>`}</div>
    </section>
    ${entries.length ? `<section class="outside-section"><div><h3>${isPac ? 'Identified direct candidate donations' : 'Candidate-attributed expenditures'}</h3><p class="chart-deck">Individual transactions from the supplied filings.</p></div><div class="table-wrap"><table><thead><tr><th>${isPac ? 'Candidate or committee' : 'Candidate benefited'}</th><th>Activity</th><th>Payee</th><th>How attributed</th><th>Date</th><th>Amount</th></tr></thead><tbody>${entries.map(profileExpenditureRow).join('')}</tbody></table></div></section>` : ''}`;
  document.querySelector('#back-advertisers').addEventListener('click', () => {
    location.hash = '';
    state.race = 'all';
    document.querySelector('#race-filter').value = 'all';
  });
  window.scrollTo({ top: view.offsetTop - 15, behavior: 'smooth' });
}

function profileCandidateName(record) {
  return record.candidate?.candidate || record.candidateName || 'Candidate named in filing';
}

function profileCandidateCard(record) {
  const positions = record.unallocated ? '<div class="position-list"><span class="position support">Support</span></div>' : advertiserPositions(record.entries);
  const amount = record.unallocated ? 'Amount unavailable' : exactMoney(record.amount);
  const content = `<div><div class="race-tag">${esc(record.candidate?.race || 'Candidate named in PAC filing')}</div><h4>${esc(profileCandidateName(record))}</h4>${positions}</div><strong>${amount}</strong>`;
  return record.candidate
    ? `<a class="advertiser-candidate-card" href="#candidate/${encodeURIComponent(record.candidate.id)}">${content}</a>`
    : `<div class="advertiser-candidate-card">${content}</div>`;
}

function profileExpenditureRow(item) {
  const candidate = state.data.find(c => c.id === item.candidateId);
  const name = candidate?.candidate || item.candidateName || 'Candidate named in filing';
  const candidateCell = candidate
    ? `<a class="table-candidate-link" href="#candidate/${encodeURIComponent(candidate.id)}"><strong>${esc(name)}</strong></a><small class="table-race">${esc(candidate.race)}</small>`
    : `<strong>${esc(name)}</strong><small class="table-race">Candidate named in PAC filing</small>`;
  return `<tr><td>${candidateCell}</td><td>${esc(item.activity)}${item.note?.includes('does not reconcile') ? '<small class="row-note">Filing allocation discrepancy</small>' : ''}</td><td>${esc(item.payee)}</td><td>${outsidePosition(item)}</td><td>${esc(item.date)}</td><td>${exactMoney(item.amount)}</td></tr>`;
}

function advertiserPositions(entries) {
  const labels = [];
  if (entries.some(item => item.allocationType === 'direct-pac-contribution')) labels.push('<span class="position pac">Direct PAC donation</span>');
  if (entries.some(item => item.position === 'support' && item.allocationType !== 'direct-pac-contribution')) labels.push('<span class="position support">Support</span>');
  for (const item of entries.filter(item => item.position === 'opposition-benefit')) {
    const target = state.data.find(c => c.id === item.targetCandidateId);
    const label = `<span class="position opposition">Benefits from opposition to ${esc(target?.candidate || 'opponent')}</span>`;
    if (!labels.includes(label)) labels.push(label);
  }
  if (entries.some(item => item.position === 'associated')) labels.push('<span class="position associated">Candidate named; stance not specified</span>');
  return `<div class="position-list">${labels.join('')}</div>`;
}

function outsidePosition(item) {
  if (item.allocationType === 'direct-pac-contribution') return '<span class="position pac">Direct PAC donation</span>';
  if (item.position === 'opposition-benefit') {
    const target = state.data.find(c => c.id === item.targetCandidateId);
    return `<span class="position opposition">Opposition to ${esc(target?.candidate || 'opponent')}</span>`;
  }
  if (item.position === 'support') return '<span class="position support">Support</span>';
  return '<span class="position associated">Candidate named; stance not specified</span>';
}

function legendRow(color, label, value, share) {
  return `<div class="legend-row"><span class="legend-dot" style="background:${color}"></span><div><strong>${esc(label)}</strong><small>${exactMoney(value)} · ${Math.round(share*100)}%</small></div></div>`;
}

function renderDonorTable(c, query = '') {
  const q = normalize(query);
  const { key, direction } = state.donorSort;
  const multiplier = direction === 'asc' ? 1 : -1;
  const list = c.donors
    .filter(d => !q || normalize(`${d.name} ${d.address}`).includes(q))
    .sort((a, b) => {
      let result;
      if (key === 'amount') result = a.amount - b.amount;
      else if (key === 'date') result = donorDateValue(a.date) - donorDateValue(b.date);
      else result = String(a[key] || '').localeCompare(String(b[key] || ''), undefined, { sensitivity: 'base' });
      return result * multiplier || a.name.localeCompare(b.name);
    });
  document.querySelector('#donor-count').textContent = `${list.length.toLocaleString()} contribution${list.length === 1 ? '' : 's'} found`;
  const shown = list.slice(0, state.donorLimit);
  document.querySelector('#donor-table').innerHTML = `<div class="table-wrap"><table><thead><tr>${donorSortHeader('name', 'Contributor')}${donorSortHeader('address', 'City and state')}${donorSortHeader('date', 'Date')}${donorSortHeader('amount', 'Amount')}</tr></thead><tbody>${shown.map(d => `<tr><td><strong>${esc(d.name)}</strong></td><td>${esc(d.address)}</td><td>${esc(d.date)}</td><td>${exactMoney(d.amount)}</td></tr>`).join('')}</tbody></table></div>${shown.length < list.length ? `<button class="load-more">Show 50 more</button>` : ''}`;
  document.querySelectorAll('#donor-table [data-sort]').forEach(button => button.addEventListener('click', () => {
    const nextKey = button.dataset.sort;
    if (state.donorSort.key === nextKey) state.donorSort.direction = state.donorSort.direction === 'asc' ? 'desc' : 'asc';
    else state.donorSort = { key: nextKey, direction: ['amount', 'date'].includes(nextKey) ? 'desc' : 'asc' };
    state.donorLimit = 50;
    renderDonorTable(c, query);
    document.querySelector(`#donor-table [data-sort="${nextKey}"]`)?.focus();
  }));
  document.querySelector('.load-more')?.addEventListener('click', () => { state.donorLimit += 50; renderDonorTable(c, query); });
}

function donorSortHeader(key, label) {
  const active = state.donorSort.key === key;
  const direction = active ? state.donorSort.direction : 'none';
  const arrow = active ? (direction === 'asc' ? '▲' : '▼') : '↕';
  const ariaSort = active ? (direction === 'asc' ? 'ascending' : 'descending') : 'none';
  return `<th aria-sort="${ariaSort}"><button class="sort-button" type="button" data-sort="${key}">${label}<span aria-hidden="true">${arrow}</span></button></th>`;
}

function donorDateValue(value) {
  const [month = 0, day = 0, year = 0] = String(value || '').split('/').map(Number);
  return (year * 10000) + (month * 100) + day;
}

init();
