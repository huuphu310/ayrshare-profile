# Profile Management API Documentation

This API provides functionality for managing profiles with network-specific states and authentication.

## API Endpoints

### 1. Get Profile (`GET /profile/{domain}/{id}/{network}`)

Handles profile creation and assignment for specific networks.

#### Parameters:
- `domain`: The domain to fetch channels from
- `id`: The channel ID
- `network`: The network type (tiktok/short)

#### Process Flow:
1. **MongoDB Query**:
   - Searches for a profile where the specified network is false
   - Query uses: `{"networks.{network}": False, "domain": domain}`

2. **Ayrshare Profile Creation**:
   - Creates profile using the fetched profile name
   - Sends POST request to "https://app.ayrshare.com/api/profiles/profile"
   - Uses form-urlencoded content type

3. **Profile Update**:
   - Updates MongoDB document with:
     - Sets network status to true
     - Stores profileKey and refId
   ```json
   {
     "networks.{network}": true,
     "profileKey": "...",
     "refId": "..."
   }
   ```

4. **Channel Update**:
   - Updates the channel in directus with profile info
   - Different URLs based on domain:
     - tcreator.cloud: `/items/idols/{id}`
     - others: `/items/channels/{id}`

5. **JWT Generation**:
   - Generates JWT URL for profile management
   - Returns 301 redirect to the JWT URL
   - If no profileKey, returns profileKey and profile info

### 2. Delete Network (`GET /delete-network/{domain}/{id}/{platform}`)

Handles network-specific deletion from profiles.

#### Parameters:
- `domain`: The domain to fetch channels from
- `id`: The channel ID
- `platform`: The platform to delete (tiktok/short)

#### Process Flow:
1. **Directus Data Fetch**:
   - Gets profile info from directus
   - Retrieves ayrshare_key and profile name

2. **Ayrshare Delete**:
   - Sends DELETE request to Ayrshare API
   - Includes platform-specific payload:
   ```json
   {
     "platform": "<platform>"
   }
   ```
   - Headers:
   ```json
   {
     "Content-Type": "application/json",
     "Authorization": "Bearer API_KEY",
     "Profile-Key": "<ayrshare_key>"
   }
   ```

3. **MongoDB Update**:
   - Sets network status to false:
   ```json
   {
     "networks.<platform>": false
   }
   ```

### 3. Delete Profile (`GET /delete-profile/{domain}/{id}`)

Legacy endpoint for complete profile deletion.

#### Parameters:
- `domain`: The domain to fetch channels from
- `id`: The channel ID

#### Process Flow:
1. **Directus Data Fetch**:
   - Gets profile info from directus
   - Retrieves ayrshare_key and profile

2. **Ayrshare Delete**:
   - Deletes entire profile from Ayrshare
   - Uses profile-specific headers

3. **MongoDB Update**:
   - Sets used status to false (legacy field)

## Database Structure

### Profile Document Structure
```json
{
  "profile": "profile_name",
  "domain": "domain_name",
  "profileKey": "ayrshare_profile_key",
  "refId": "reference_id",
  "networks": {
    "tiktok": false,
    "short": false
  }
}
```

## Environment Variables
- `MONGODB_URI`: MongoDB connection string
- `AYRSHARE_API_KEY`: API key for Ayrshare
- `DATABASE_NAME`: Name of the MongoDB database
- `DIRECTUS_AUTH_TOKEN`: Authentication token for Directus

## Error Handling
- Returns 404 for missing tokens or profiles
- Returns 500 for API call failures
- Returns 400 for invalid profile data
- All errors include detailed error messages

## Authentication
- Uses bearer token authentication for Directus
- Uses API key authentication for Ayrshare
- Supports JWT-based profile management interface

## Additional Features
- Supports multiple domains (tcreator.cloud and others)
- Uses thread pool executor for blocking operations
- Maintains global token cache for performance
