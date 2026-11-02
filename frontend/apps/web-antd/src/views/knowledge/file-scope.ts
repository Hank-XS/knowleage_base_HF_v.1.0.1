import { computed, onBeforeUnmount, ref } from 'vue';
import { getCatalog, type CatalogOptions } from '#/api/catalog';
import { getKmDoc, listKmDocs, type KmDoc } from '#/api/kb';

export function useFileScope() {
  const catalog = ref<CatalogOptions>({ libraries: [], projects: [], purposes: [], tags: [] });
  const library = ref(''); const project = ref(''); const tag = ref(''); const fileId = ref(''); const file = ref<KmDoc>();
  const page = ref(1); const total = ref(0); const search = ref(''); const loading = ref(false);
  const files = ref<{ label: string; value: string }[]>([]); let timer: ReturnType<typeof setTimeout> | undefined; let sequence = 0;
  const records = ref<KmDoc[]>([]); let catalogSequence = 0;
  const systems = computed(() => catalog.value.libraries.flatMap(l => [{ label: l.title, value: l.key }, ...(l.children || []).map(c => ({ label: `${l.title} / ${c.title}`, value: c.key }))]));
  const projects = computed(() => [...new Set(catalog.value.projects.filter(p => !library.value || p.library === library.value || p.library.startsWith(library.value + '/')).map(p => p.name))].map(name => ({ label: name, value: name })));
  function label(d: KmDoc) { return d.name.toLowerCase().endsWith('.' + d.type.toLowerCase()) ? d.name : `${d.name}.${d.type}`; }
  async function loadFiles(extra: Record<string, any> = {}, append = false) {
    const id = ++sequence; loading.value = true;
    try {
      const result = await listKmDocs({ kb: library.value, project: project.value, tag: tag.value, keyword: search.value, page: page.value, page_size: 30, ...extra });
      if (id !== sequence) return;
      records.value = append ? [...new Map([...records.value, ...result.items].map(d => [d.id, d])).values()] : result.items;
      files.value = records.value.map(d => ({ label: label(d), value: d.id })); total.value = result.total;
      if (file.value && (!library.value || file.value.path === library.value || file.value.path.startsWith(library.value + '/')) && (!project.value || file.value.project === project.value) && (!tag.value || file.value.tags?.includes(tag.value)) && !files.value.some(f => f.value === file.value?.id)) files.value.unshift({ label: label(file.value), value: file.value.id });
    } finally { if (id === sequence) loading.value = false; }
  }
  async function initialize(query: Record<string, any> = {}, extra: Record<string, any> = {}) {
    library.value = String(query.library || query.kb || library.value || ''); project.value = String(query.project || project.value || ''); tag.value = String(query.tag || tag.value || '');
    if (query.doc) { fileId.value = String(query.doc); file.value = await getKmDoc(fileId.value); library.value = file.value.path; project.value = file.value.project || ''; }
    await refreshOptions(); await loadFiles(extra);
  }
  async function refreshOptions() { const request = ++catalogSequence; const data = await getCatalog({ kb: library.value, project: project.value }); if (request !== catalogSequence) return; catalog.value = data; if (tag.value && !catalog.value.tags.some(t => t.value === tag.value)) tag.value = ''; }
  async function reset(resetProject: boolean, extra: Record<string, any> = {}) { if (resetProject) project.value = ''; fileId.value = ''; file.value = undefined; page.value = 1; search.value = ''; await refreshOptions(); await loadFiles(extra); }
  function searchFiles(value: string, extra: Record<string, any> = {}) { clearTimeout(timer); timer = setTimeout(() => { search.value = value; page.value = 1; void loadFiles(extra); }, 250); }
  async function loadMore(event: Event, extra: Record<string, any> = {}) { const el = event.target as HTMLElement; if (!loading.value && records.value.length < total.value && el.scrollTop + el.clientHeight >= el.scrollHeight - 30) { page.value++; await loadFiles(extra, true); } }
  onBeforeUnmount(() => { clearTimeout(timer); sequence++; });
  return { catalog, library, project, tag, fileId, file, page, total, files, records, search, loading, systems, projects, loadFiles, loadMore, refreshOptions, initialize, reset, searchFiles };
}
