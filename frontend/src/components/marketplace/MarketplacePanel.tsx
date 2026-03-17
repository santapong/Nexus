import { useState } from 'react'
import {
  useMarketplaceListings,
  useCreateListing,
  usePublishListing,
} from '../../hooks/useMarketplace'

function StarRating({ rating }: { rating: number }) {
  const full = Math.floor(rating)
  const half = rating - full >= 0.5
  const empty = 5 - full - (half ? 1 : 0)
  return (
    <span className="text-yellow-400 text-sm">
      {'★'.repeat(full)}
      {half ? '☆' : ''}
      {'☆'.repeat(empty)}
      <span className="text-gray-500 text-xs ml-1">({rating.toFixed(1)})</span>
    </span>
  )
}

export function MarketplacePanel() {
  const [skillFilter, setSkillFilter] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [skills, setSkills] = useState('')
  const [price, setPrice] = useState('')

  const { data: listings, isLoading } = useMarketplaceListings(
    skillFilter || undefined
  )
  const createListing = useCreateListing()
  const publishListing = usePublishListing()

  const handleCreate = () => {
    const skillList = skills
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    const priceNum = parseFloat(price)
    if (!name.trim() || !description.trim() || skillList.length === 0 || isNaN(priceNum)) {
      return
    }
    createListing.mutate(
      {
        name,
        description,
        skills: skillList,
        price_per_task_usd: priceNum,
      },
      {
        onSuccess: () => {
          setName('')
          setDescription('')
          setSkills('')
          setPrice('')
          setShowCreate(false)
        },
      }
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <span className="text-2xl">🏪</span> Agent Marketplace
        </h2>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="px-3 py-1 text-xs bg-indigo-600 text-white rounded-md hover:bg-indigo-500 transition-all"
        >
          {showCreate ? 'Cancel' : 'Create Listing'}
        </button>
      </div>

      {/* Skill filter */}
      <div>
        <input
          value={skillFilter}
          onChange={(e) => setSkillFilter(e.target.value)}
          placeholder="Filter by skill (e.g., python, research)"
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
        />
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3">
          <div>
            <label className="text-xs text-gray-400 block mb-1">Listing Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Python Code Expert"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe what this agent listing offers..."
              rows={3}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none resize-none"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-400 block mb-1">
                Skills (comma-separated)
              </label>
              <input
                value={skills}
                onChange={(e) => setSkills(e.target.value)}
                placeholder="python, code, debug"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 block mb-1">
                Price per Task (USD)
              </label>
              <input
                type="number"
                step="0.01"
                min="0"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder="0.50"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
              />
            </div>
          </div>
          <button
            onClick={handleCreate}
            disabled={createListing.isPending}
            className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 disabled:opacity-50 transition-all"
          >
            {createListing.isPending ? 'Creating...' : 'Create Listing'}
          </button>
        </div>
      )}

      {/* Listings grid */}
      {isLoading ? (
        <div className="text-gray-500 text-sm animate-pulse">Loading listings...</div>
      ) : listings && listings.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {listings.map((listing) => (
            <div
              key={listing.id}
              className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3 hover:border-gray-700 transition-colors"
            >
              <div className="flex items-start justify-between">
                <h3 className="text-white font-semibold text-sm">{listing.name}</h3>
                <span
                  className={`px-2 py-0.5 rounded text-xs font-medium ${
                    listing.is_published
                      ? 'bg-green-950/50 text-green-400'
                      : 'bg-yellow-950/50 text-yellow-400'
                  }`}
                >
                  {listing.is_published ? 'Published' : 'Draft'}
                </span>
              </div>

              <p className="text-gray-400 text-xs line-clamp-2">{listing.description}</p>

              <div className="flex flex-wrap gap-1">
                {listing.skills.map((skill) => (
                  <span
                    key={skill}
                    className="px-1.5 py-0.5 bg-gray-800 text-gray-300 rounded text-xs"
                  >
                    {skill}
                  </span>
                ))}
              </div>

              <div className="flex items-center justify-between">
                <StarRating rating={listing.rating} />
                <span className="text-gray-500 text-xs">
                  {listing.total_reviews} reviews
                </span>
              </div>

              <div className="flex items-center justify-between border-t border-gray-800 pt-3">
                <div>
                  <span className="text-white font-semibold text-sm">
                    ${listing.price_per_task_usd.toFixed(2)}
                  </span>
                  <span className="text-gray-500 text-xs ml-1">/ task</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-gray-500 text-xs">
                    {listing.total_tasks_completed} tasks done
                  </span>
                  {!listing.is_published && (
                    <button
                      onClick={() => publishListing.mutate(listing.id)}
                      disabled={publishListing.isPending}
                      className="px-2 py-1 text-xs bg-green-800/50 text-green-300 rounded hover:bg-green-700/50 disabled:opacity-50 transition-all"
                    >
                      Publish
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-gray-500 text-sm">
          No marketplace listings found. Create one to get started.
        </div>
      )}
    </div>
  )
}
