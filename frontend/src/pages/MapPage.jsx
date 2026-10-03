import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { AtlasExplorer } from '@shizuha/atlas'
import { indexAtlas } from '@shizuha/atlas/core'
import { atlasApi, backToLibrary } from '../api'

export default function MapPage() {
  const { mapId } = useParams()
  const location = useLocation()
  const library = backToLibrary(location.state?.library)
  const [map, setMap] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    atlasApi(`/maps/${mapId}`).then(payload => {
      if (payload.model) indexAtlas(payload.model)
      if (live) setMap(payload)
    }).catch(failure => {
      if (live) setError(failure.message)
    })
    return () => { live = false }
  }, [mapId])

  return (
    <main className="shell map-shell">
      <header className="bar">
        <a className="button library-back" href={library}>Maps</a>
        <div className="brand"><p className="kicker">Atlas</p><strong>{map?.title || 'Map'}</strong></div>
        <div className="actions">
          {map && map.kind !== 'system' && <Link className="button" to={`/editor/${map.id}`} state={{ library: location.state?.library }}>Edit</Link>}
        </div>
      </header>
      <section className="stage">
        {error && <div className="empty-state"><h1>This map is not available</h1><p>{error}</p></div>}
        {!error && !map && <p className="home empty">Opening the map…</p>}
        {map?.model && <div className="canvas"><AtlasExplorer model={map.model} backHref="/" backLabel="All maps" /></div>}
      </section>
    </main>
  )
}
