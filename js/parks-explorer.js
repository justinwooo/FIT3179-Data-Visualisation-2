(async function () {
  const status = document.getElementById('status');
  const mapEl = document.getElementById('parkMap');
  const category = document.getElementById('category');
  const municipality = document.getElementById('municipality');
  const ROOT_SCALE = 19000;
  let view;
  try {
    const response = await fetch('data/processed/parks_explorer_focus.json');
    if (!response.ok) throw new Error('Missing focus list: '+response.status);
    const locations = await response.json();
    for (const place of locations.slice(1)) {
      const opt = document.createElement('option');
      opt.value = place.value;
      opt.textContent = place.label;
      municipality.appendChild(opt);
    }
    const result = await vegaEmbed('#parkMap', 'charts/00_parks_explorer.vega.json', {
      actions: false, renderer: 'canvas'
    });
    view = result.view;
    status.textContent = 'Mapped public green-space parcels in four categories.';
    const render = () => view.runAsync();
    category.addEventListener('change', () => {
      view.signal('chosenCategory', category.value); render();
    });
    function focusOn(place) {
      const [w,s,e,n] = place.bounds;
      const lon = (w+e)/2, lat = (s+n)/2;
      // Mercator metres in Vega projection are scaled radians; correct for latitude.
      const projectedH = Math.abs(Math.log(Math.tan(Math.PI/4 + n*Math.PI/360)) - Math.log(Math.tan(Math.PI/4 + s*Math.PI/360)));
      const projectedW = Math.abs((e-w)*Math.PI/180);
      const targetWidth = Math.max(500, Math.min(mapEl.clientWidth-30, 1000));
      const nextScale = Math.min(600000, Math.max(1000, Math.min(targetWidth*0.85/Math.max(projectedW,0.001), 610*0.85/Math.max(projectedH,0.001))));
      view.signal('centerLon',lon).signal('centerLat',lat).signal('mapScale',place.value==='ALL' ? ROOT_SCALE : nextScale);
      render();
    }
    // Click a municipality region or a park polygon to focus on its LGA.
    // This replaces drag-to-pan entirely.
    view.addEventListener('click', (_event, item) => {
      if (!item || !item.datum || !item.datum.properties) return;
      const props = item.datum.properties;
      // Park features use lga_key; LGA features use lga_code/lga_name.
      let key = props.lga_key;
      if (!key && props.lga_name) {
        const normalise = s => s.toUpperCase().replace(/\s*\([^)]*\)/g, '').replace(/[^A-Z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
        key = normalise(props.lga_name);
        if (key === 'MORNINGTON') key = 'MORNINGTON PENINSULA';
      }
      const place = locations.find(p => p.value === key);
      if (!place) return;
      municipality.value = place.value;
      view.signal('chosenLga', place.value);
      focusOn(place);
    });
    municipality.addEventListener('change',()=>{
      view.signal('chosenLga',municipality.value);
      const place = locations.find(x=>x.value===municipality.value);
      if (place) focusOn(place);
      else render();
    });
    document.getElementById('zoomIn').addEventListener('click',()=>{view.signal('mapScale',Math.min(900000,view.signal('mapScale')*1.6));render();});
    document.getElementById('zoomOut').addEventListener('click',()=>{view.signal('mapScale',Math.max(1000,view.signal('mapScale')/1.6));render();});
    document.getElementById('reset').addEventListener('click',()=>{
      category.value='All categories';municipality.value='ALL';
      view.signal('chosenCategory','All categories').signal('chosenLga','ALL');
      view.signal('centerLon',145.25).signal('centerLat',-37.95).signal('mapScale',ROOT_SCALE);render();
    });
  } catch(err){
    status.textContent='Map failed to load: '+err.message;
    console.error('Parks explorer:',err);
  }
})();
